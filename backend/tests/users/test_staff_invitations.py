"""Invitation status and "Resend invite": `GET /users/staff` and `POST /users/staff/{id}/invitation`.

Contract: `docs/features/03-users-and-roles/03-design.md`, "As built: the `INVITED` status", and
`docs2/sdlc/01-auth-and-shell/api.md`. A pending invitation is the account's `INVITED` state; a resend
issues a fresh single-use link, retires the previous one and restarts the window, and is checked
exactly like the invitation (`users:manage`, then R3 over the roles the person holds).

The denial path comes first (`docs/reference/definition-of-done.md` §9): no session, no
`users:manage`, another organisation's account, a role beyond the caller's, an invitation that is no
longer outstanding, no outgoing mail and the rate limit all refuse and change nothing (the old link
still works, no email goes out). Then the success path, and the same-transaction audit.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.core.rate_limit import limiter
from app.modules.users_roles import invitations, service
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
STAFF_URL = f"{API}/users/staff"
ACCEPT_URL = f"{API}/users/invitations/accept"
LOGIN_URL = f"{API}/login/access-token"
NEW_PASSWORD = "a-brand-new-passphrase"
WINDOW = timedelta(hours=settings.STAFF_INVITATION_EXPIRE_HOURS)


def _resend_url(user_id: object) -> str:
    return f"{STAFF_URL}/{user_id}/invitation"


@dataclass
class Outbox:
    """Every email the app tried to send, in order."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def tokens_for(self, email: str) -> list[str]:
        found = []
        for message in self.sent:
            if message["email_to"] == email:
                link = re.search(
                    r"/accept-invite\?token=([A-Za-z0-9._-]+)", message["html_content"]
                )
                assert link, "the invitation email carries no accept link"
                found.append(link.group(1))
        return found


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    box = Outbox()

    def capture(**message: Any) -> None:
        box.sent.append(message)

    with patch("app.utils.send_email", side_effect=capture):
        yield box


@dataclass(frozen=True)
class Invited:
    owner: ActorSession
    user_id: str
    email: str
    token: str


def _invite(rbac: RbacApi, outbox: Outbox, *codes: str, clinic: str) -> Invited:
    owner = rbac.register_tenant(clinic_name=clinic)
    assert owner.tenant_id is not None
    email = f"invitee-{uuid.uuid4()}@example.com"
    body = {
        "email": email,
        "full_name": "Ira Invitee",
        "role_ids": [
            str(rbac.role_id_for(tenant_id=owner.tenant_id, code=code))
            for code in codes or ("NURSE",)
        ],
    }
    created = rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
    assert created.status_code == 201, created.text
    (token,) = outbox.tokens_for(email)
    return Invited(owner, created.json()["id"], email, token)


def _hash(user_id: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text('SELECT hashed_password FROM "user" WHERE id = :id'),
                {"id": user_id},
            ).scalar_one()
        )


def _row(user_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT * FROM staff_invitations WHERE user_id = :id"),
                {"id": user_id},
            )
            .mappings()
            .one()
        )


def _resend_events(tenant_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """The tenant's resend events (`user.create` carrying `change`), oldest first, as the owner."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT result, reason, actor_id, resource_id, metadata AS payload, request_id"
                " FROM audit_log WHERE tenant_id = :tenant_id AND action = 'user.create'"
                " AND metadata ? 'change' ORDER BY timestamp, event_id"
            ),
            {"tenant_id": tenant_id},
        ).mappings()
        return [dict(row) for row in rows]


def _member(rbac: RbacApi, owner: ActorSession, user_id: str) -> dict[str, Any]:
    listed = rbac.client.get(STAFF_URL, headers=owner.headers)
    assert listed.status_code == 200, listed.text
    (member,) = [m for m in listed.json()["data"] if m["id"] == user_id]
    return member


def _accept(client: TestClient, token: str) -> int:
    response = client.post(
        ACCEPT_URL, json={"token": token, "new_password": NEW_PASSWORD}
    )
    return response.status_code


def _code(response: Any) -> str:
    return str(response.json()["detail"]["code"])


# --- Denial path -------------------------------------------------------------------------------


def test_no_session_is_401(client: TestClient) -> None:
    assert client.post(_resend_url(uuid.uuid4())).status_code == 401


def test_without_users_manage_is_403_audited_and_changes_nothing(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, clinic="Resend Denial Clinic")
    assert invited.owner.tenant_id is not None
    doctor = rbac.add_actor(
        tenant_id=invited.owner.tenant_id,
        granted_by=invited.owner.user_id,
        role_code="DOCTOR",
    )
    before = _hash(invited.user_id)

    refused = rbac.client.post(_resend_url(invited.user_id), headers=doctor.headers)
    assert refused.status_code == 403
    assert _code(refused) == "PERMISSION_NOT_HELD"
    assert _hash(invited.user_id) == before
    assert len(outbox.sent) == 1, "a refused resend sent an email"

    (event,) = _resend_events(invited.owner.tenant_id)
    assert (event["result"], event["reason"]) == ("DENIED", "PERMISSION_NOT_HELD")
    assert event["actor_id"] == doctor.user_id
    # Decided before the lookup, so the trail names no account the caller merely typed.
    assert event["payload"] == {"change": "INVITATION_RESENT", "step_up": False}
    assert event["resource_id"] is None


def test_another_organisations_account_is_404_and_changes_nothing(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, clinic="Resend Clinic A")
    other = rbac.register_tenant(clinic_name="Resend Clinic B")
    before = _hash(invited.user_id)

    for target in (invited.user_id, uuid.uuid4()):
        response = rbac.client.post(_resend_url(target), headers=other.headers)
        assert response.status_code == 404
        assert response.json()["detail"] == "Staff member not found"
    assert _hash(invited.user_id) == before
    assert len(outbox.sent) == 1
    assert _resend_events(invited.owner.tenant_id) == []
    assert _resend_events(other.tenant_id) == []
    # The original link still works: nothing was retired.
    assert _accept(rbac.client, invited.token) == 200


def test_a_role_beyond_the_callers_own_is_403_audited(
    rbac: RbacApi, outbox: Outbox
) -> None:
    """Resending is re-inviting: whoever could not have invited the person cannot resend it."""
    invited = _invite(rbac, outbox, "DOCTOR", clinic="Resend Escalation Clinic")
    assert invited.owner.tenant_id is not None
    admin = rbac.add_actor(
        tenant_id=invited.owner.tenant_id,
        granted_by=invited.owner.user_id,
        role_code="ADMINISTRATOR",
    )
    before = _hash(invited.user_id)

    refused = rbac.client.post(_resend_url(invited.user_id), headers=admin.headers)
    assert refused.status_code == 403
    assert _code(refused) == "GRANT_EXCEEDS_ACTOR"
    assert _hash(invited.user_id) == before
    assert len(outbox.sent) == 1

    (event,) = _resend_events(invited.owner.tenant_id)
    assert (event["result"], event["reason"]) == ("DENIED", "GRANT_EXCEEDS_ACTOR")
    assert event["payload"] == {
        "change": "INVITATION_RESENT",
        "target_user_id": invited.user_id,
        "step_up": False,
    }


def test_an_invitation_that_is_no_longer_outstanding_is_409(
    rbac: RbacApi, outbox: Outbox
) -> None:
    accepted = _invite(rbac, outbox, clinic="Resend Accepted Clinic")
    owner = accepted.owner
    assert _accept(rbac.client, accepted.token) == 200
    accepted_hash = _hash(accepted.user_id)

    # A password set through recovery ends the invitation too (the row was never told).
    recovered = _invite(rbac, outbox, clinic="Resend Recovered Clinic")
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE "user" SET hashed_password = :h WHERE id = :id'),
            {"h": invitations.unusable_password_hash(), "id": recovered.user_id},
        )
    deactivated = _invite(rbac, outbox, clinic="Resend Deactivated Clinic")
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE "user" SET is_active = false WHERE id = :id'),
            {"id": deactivated.user_id},
        )
    sent = len(outbox.sent)

    cases = [
        (owner, accepted.user_id, "ACTIVE"),
        # The founder never had an invitation.
        (owner, str(owner.user_id), "ACTIVE"),
        (recovered.owner, recovered.user_id, "ACTIVE"),
        (deactivated.owner, deactivated.user_id, "INACTIVE"),
    ]
    for actor, user_id, status in cases:
        member = _member(rbac, actor, user_id)
        assert (member["status"], member["invitation"]) == (status, None), user_id
        refused = rbac.client.post(_resend_url(user_id), headers=actor.headers)
        assert refused.status_code == 409, user_id
        assert _code(refused) == "INVITATION_NOT_PENDING"

    # Above all, a resend never replaced the password the person chose.
    assert _hash(accepted.user_id) == accepted_hash
    assert len(outbox.sent) == sent
    events = _resend_events(owner.tenant_id)
    assert [(e["result"], e["reason"]) for e in events] == [
        ("DENIED", "INVITATION_NOT_PENDING")
    ] * 2
    assert {e["payload"]["target_user_id"] for e in events} == {
        accepted.user_id,
        str(owner.user_id),
    }


def test_no_outgoing_mail_is_503_and_changes_nothing(
    rbac: RbacApi, outbox: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    invited = _invite(rbac, outbox, clinic="Resend No Mail Clinic")
    before = _hash(invited.user_id)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    response = rbac.client.post(
        _resend_url(invited.user_id), headers=invited.owner.headers
    )
    assert response.status_code == 503
    assert _code(response) == "EMAIL_NOT_CONFIGURED"
    assert _hash(invited.user_id) == before
    assert _resend_events(invited.owner.tenant_id) == []


def test_resending_is_rate_limited_like_the_invitation(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, clinic="Resend Rate Clinic")
    limiter.clear()
    statuses = [
        rbac.client.post(
            _resend_url(uuid.uuid4()), headers=invited.owner.headers
        ).status_code
        for _ in range(21)
    ]
    assert statuses == [404] * 20 + [429]
    # The window is the administrative class's, shared with the staff list and the invitation.
    assert rbac.client.get(STAFF_URL, headers=invited.owner.headers).status_code == 429


def test_a_failed_audit_write_or_email_changes_nothing(
    rbac: RbacApi, outbox: Outbox
) -> None:
    """INV-4: the new link, its audit event and its email are one unit."""
    invited = _invite(rbac, outbox, clinic="Resend Atomic Clinic")
    before_hash, before_row = _hash(invited.user_id), _row(invited.user_id)
    real_record = service.audit.record

    def refuse_resend(session: Any, event: Any) -> Any:
        if event.result == "SUCCESS" and event.payload.get("change"):
            raise service.audit.AuditWriteRefused("simulated")
        return real_record(session, event)

    with (
        patch.object(service.audit, "record", side_effect=refuse_resend),
        pytest.raises(service.audit.AuditWriteRefused),
    ):
        rbac.client.post(_resend_url(invited.user_id), headers=invited.owner.headers)
    with (
        patch("app.utils.send_email", side_effect=ConnectionError("smtp down")),
        pytest.raises(ConnectionError),
    ):
        rbac.client.post(_resend_url(invited.user_id), headers=invited.owner.headers)

    assert _hash(invited.user_id) == before_hash
    assert _row(invited.user_id) == before_row
    assert len(outbox.sent) == 1
    assert _resend_events(invited.owner.tenant_id) == []
    assert _accept(rbac.client, invited.token) == 200, "the old link was retired"


# --- Success path ------------------------------------------------------------------------------


def test_the_list_shows_an_outstanding_invitation_until_it_is_accepted(
    rbac: RbacApi, outbox: Outbox
) -> None:
    started = datetime.now(UTC)
    invited = _invite(rbac, outbox, clinic="Status Clinic")

    member = _member(rbac, invited.owner, invited.user_id)
    assert member["status"] == "INVITED"
    assert member["is_active"] is True
    pending = member["invitation"]
    sent_at = datetime.fromisoformat(pending["sent_at"])
    assert started <= sent_at <= datetime.now(UTC)
    assert datetime.fromisoformat(pending["expires_at"]) == sent_at + WINDOW
    assert pending["expired"] is False
    owner = _member(rbac, invited.owner, str(invited.owner.user_id))
    assert (owner["status"], owner["invitation"]) == ("ACTIVE", None)

    # Once the window has passed the invitation is still outstanding, and says it has expired.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE staff_invitations SET sent_at = sent_at - :shift,"
                " expires_at = expires_at - :shift WHERE user_id = :id"
            ),
            {"shift": WINDOW + timedelta(minutes=1), "id": invited.user_id},
        )
    expired = _member(rbac, invited.owner, invited.user_id)
    assert (expired["status"], expired["invitation"]["expired"]) == ("INVITED", True)

    # Accepting answers it: the row records when, and the list shows the person as active.
    resent = rbac.client.post(
        _resend_url(invited.user_id), headers=invited.owner.headers
    )
    assert resent.status_code == 200, resent.text
    assert _accept(rbac.client, outbox.tokens_for(invited.email)[-1]) == 200
    assert _row(invited.user_id)["accepted_at"] is not None
    accepted = _member(rbac, invited.owner, invited.user_id)
    assert (accepted["status"], accepted["invitation"]) == ("ACTIVE", None)


def test_resend_issues_a_new_link_and_retires_the_old_one(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, "DOCTOR", "NURSE", clinic="Resend Clinic")
    first_sent = _row(invited.user_id)["sent_at"]

    resent = rbac.client.post(
        _resend_url(invited.user_id), headers=invited.owner.headers
    )
    assert resent.status_code == 200, resent.text
    member = resent.json()
    assert member["status"] == "INVITED"
    assert [role["code"] for role in member["roles"]] == ["DOCTOR", "NURSE"]
    assert "hashed_password" not in member and "tenant_id" not in member
    new_sent = datetime.fromisoformat(member["invitation"]["sent_at"])
    assert new_sent > first_sent
    assert datetime.fromisoformat(member["invitation"]["expires_at"]) == (
        new_sent + WINDOW
    )
    assert member["invitation"]["expired"] is False

    # One more email, to the invitee, the invitation email again: name, clinic and link.
    first, second = outbox.tokens_for(invited.email)
    assert first == invited.token and second != first
    message = outbox.sent[-1]
    assert message["email_to"] == invited.email
    assert "Resend Clinic" in message["subject"]
    assert "Ira Invitee" in message["html_content"]

    # The old link is refused like a used one; the new one works, once.
    old = rbac.client.post(
        ACCEPT_URL, json={"token": first, "new_password": NEW_PASSWORD}
    )
    assert old.status_code == 400
    assert _code(old) == "INVITATION_INVALID"
    assert _accept(rbac.client, second) == 200
    assert _accept(rbac.client, second) == 400
    signed_in = rbac.client.post(
        LOGIN_URL, data={"username": invited.email, "password": NEW_PASSWORD}
    )
    assert signed_in.status_code == 200


def test_a_resend_is_audited_in_the_same_transaction(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, clinic="Resend Audit Clinic")
    resent = rbac.client.post(
        _resend_url(invited.user_id), headers=invited.owner.headers
    )
    assert resent.status_code == 200, resent.text

    (event,) = _resend_events(invited.owner.tenant_id)
    assert (event["result"], event["reason"]) == ("SUCCESS", None)
    assert event["actor_id"] == invited.owner.user_id
    assert str(event["resource_id"]) == invited.user_id
    assert event["payload"] == {
        "target_user_id": invited.user_id,
        "change": "INVITATION_RESENT",
        "step_up": False,
    }
    # The event and the new link are one request's work, and the row names who sent the link.
    assert event["request_id"] is not None
    assert _row(invited.user_id)["invited_by"] == invited.owner.user_id


def test_an_administrator_can_resend_an_invitation_into_a_role_they_hold(
    rbac: RbacApi, outbox: Outbox
) -> None:
    invited = _invite(rbac, outbox, "ADMINISTRATOR", clinic="Resend Admin Clinic")
    assert invited.owner.tenant_id is not None
    admin = rbac.add_actor(
        tenant_id=invited.owner.tenant_id,
        granted_by=invited.owner.user_id,
        role_code="ADMINISTRATOR",
    )
    resent = rbac.client.post(_resend_url(invited.user_id), headers=admin.headers)
    assert resent.status_code == 200, resent.text
    assert _row(invited.user_id)["invited_by"] == admin.user_id
    assert _accept(rbac.client, outbox.tokens_for(invited.email)[-1]) == 200
