"""Staff directory and onboarding: `GET`/`POST /api/v1/users/staff`, `POST /users/invitations/accept`.

Design: `docs/features/03-users-and-roles/03-design.md` "Endpoints" (`GET /users` "tenant-scoped
list", `POST /users` "invite; `409` duplicate email; `422`/`403` role not grantable"), R3, R6, R10,
R12; `02-user-stories.md` US-3; `04-threat-model.md` T-03.2 and T-03.8. The routes live under
`/users/staff` because the legacy, superuser-only `/users/` already owns the bare path.

The denial path is asserted first (`docs/reference/definition-of-done.md` §9): no session, no
`users:manage`, another tenant's role, a client-supplied `tenant_id`, a role the caller may not grant
and a taken address all fail closed and write nothing but their audit event. Then the success path
end to end: invite, email, accept once, sign in, land in the right organisation with the right
permissions.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.modules.users_roles import invitations, service
from app.modules.users_roles.catalog import SYSTEM_ROLE_CATALOGUE
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
STAFF_URL = f"{API}/users/staff"
ACCEPT_URL = f"{API}/users/invitations/accept"
LOGIN_URL = f"{API}/login/access-token"
BUNDLES = {code: sorted(bundle) for code, _name, bundle in SYSTEM_ROLE_CATALOGUE}
NEW_PASSWORD = "a-brand-new-passphrase"


@dataclass
class Outbox:
    """Every invitation email the app tried to send, in order."""

    sent: list[dict[str, Any]] = field(default_factory=list)

    def token_for(self, email: str) -> str:
        for message in reversed(self.sent):
            if message["email_to"] == email:
                found = re.search(
                    r"/accept-invite\?token=([A-Za-z0-9._-]+)", message["html_content"]
                )
                assert found, "the invitation email carries no accept link"
                return found.group(1)
        raise AssertionError(f"no invitation was sent to {email}")


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    box = Outbox()

    def capture(**message: Any) -> None:
        box.sent.append(message)

    with patch("app.utils.send_email", side_effect=capture):
        yield box


def _role_id(rbac: RbacApi, actor: ActorSession, code: str) -> str:
    assert actor.tenant_id is not None
    return str(rbac.role_id_for(tenant_id=actor.tenant_id, code=code))


def _invite_body(
    rbac: RbacApi, actor: ActorSession, *codes: str, email: str | None = None
) -> dict[str, Any]:
    return {
        "email": email or f"staff-{uuid.uuid4()}@example.com",
        "full_name": "Dana Staff",
        "role_ids": [_role_id(rbac, actor, code) for code in codes or ("DOCTOR",)],
    }


def _audit(
    tenant_id: uuid.UUID | None, action: str = "user.create"
) -> list[dict[str, Any]]:
    """The tenant's events for one action, oldest first, read as the owner (bypasses RLS)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT action, result, reason, actor_id, resource_id, metadata AS payload, request_id"
                " FROM audit_log WHERE tenant_id = :tenant_id AND action = :action"
                " ORDER BY timestamp, event_id"
            ),
            {"tenant_id": tenant_id, "action": action},
        ).mappings()
        return [dict(row) for row in rows]


def _account(email: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    'SELECT id, tenant_id, is_active FROM "user" WHERE lower(email) = lower(:email)'
                ),
                {"email": email},
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)


def _code(response: Any) -> str:
    return str(response.json()["detail"]["code"])


# --- Denial path -------------------------------------------------------------------------------


def test_no_session_is_401(client: TestClient) -> None:
    assert client.get(STAFF_URL).status_code == 401
    body = {"email": "x@example.com", "full_name": "X", "role_ids": [str(uuid.uuid4())]}
    assert client.post(STAFF_URL, json=body).status_code == 401


def test_without_users_manage_is_403_audited_and_creates_nothing(
    rbac: RbacApi, outbox: Outbox
) -> None:
    owner = rbac.register_tenant(clinic_name="Staff Denial Clinic")
    assert owner.tenant_id is not None
    doctor = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="DOCTOR"
    )

    listed = rbac.client.get(STAFF_URL, headers=doctor.headers)
    assert listed.status_code == 403
    assert _code(listed) == "PERMISSION_NOT_HELD"

    body = _invite_body(rbac, owner, "NURSE")
    refused = rbac.client.post(STAFF_URL, json=body, headers=doctor.headers)
    assert refused.status_code == 403
    assert _code(refused) == "PERMISSION_NOT_HELD"
    assert _account(body["email"]) is None
    assert outbox.sent == []

    (event,) = _audit(owner.tenant_id)
    assert (event["result"], event["reason"]) == ("DENIED", "PERMISSION_NOT_HELD")
    assert event["actor_id"] == doctor.user_id


def test_an_account_with_no_organisation_is_refused(rbac: RbacApi) -> None:
    loner = rbac.register_tenant(clinic_name=None)
    response = rbac.client.get(STAFF_URL, headers=loner.headers)
    assert response.status_code == 403
    assert _code(response) == "NO_ORGANISATION"


def test_another_tenants_staff_are_invisible(rbac: RbacApi, outbox: Outbox) -> None:
    clinic_a = rbac.register_tenant(clinic_name="Staff Clinic A")
    clinic_b = rbac.register_tenant(clinic_name="Staff Clinic B")
    assert clinic_a.tenant_id is not None
    a_nurse = rbac.add_actor(
        tenant_id=clinic_a.tenant_id, granted_by=clinic_a.user_id, role_code="NURSE"
    )

    seen_by_b = rbac.client.get(STAFF_URL, headers=clinic_b.headers).json()
    ids = {member["id"] for member in seen_by_b["data"]}
    assert ids == {str(clinic_b.user_id)}
    assert seen_by_b["count"] == 1
    assert str(a_nurse.user_id) not in ids

    # A tenant-A role id named by tenant B is `404`, never `403`: it looks absent.
    body = _invite_body(rbac, clinic_a, "NURSE")
    crossed = rbac.client.post(STAFF_URL, json=body, headers=clinic_b.headers)
    assert crossed.status_code == 404
    assert _account(body["email"]) is None
    assert outbox.sent == []

    # A `tenant_id` query parameter on the list is never read.
    forged = rbac.client.get(
        STAFF_URL,
        params={"tenant_id": str(clinic_a.tenant_id)},
        headers=clinic_b.headers,
    )
    assert {member["id"] for member in forged.json()["data"]} == {str(clinic_b.user_id)}


@pytest.mark.usefixtures("outbox")
def test_a_client_tenant_id_is_ignored_and_audited(rbac: RbacApi) -> None:
    clinic_a = rbac.register_tenant(clinic_name="Forged Tenant Target")
    clinic_b = rbac.register_tenant(clinic_name="Forged Tenant Caller")
    body = _invite_body(rbac, clinic_b, "NURSE") | {
        "tenant_id": str(clinic_a.tenant_id)
    }

    created = rbac.client.post(STAFF_URL, json=body, headers=clinic_b.headers)
    assert created.status_code == 201, created.text
    account = _account(body["email"])
    assert account is not None
    assert account["tenant_id"] == clinic_b.tenant_id, (
        "the invitation followed the client tenant_id"
    )

    events = _audit(clinic_b.tenant_id)
    assert [(e["result"], e["reason"]) for e in events] == [
        ("DENIED", "CLIENT_TENANT_ID_IGNORED"),
        ("SUCCESS", None),
    ]
    assert len({e["request_id"] for e in events}) == 1, (
        "the two events are one request's"
    )
    assert _audit(clinic_a.tenant_id) == [], "nothing was written to the named tenant"

    # The same in the query string.
    query = _invite_body(rbac, clinic_b, "NURSE")
    via_query = rbac.client.post(
        STAFF_URL,
        json=query,
        params={"tenant_id": str(clinic_a.tenant_id)},
        headers=clinic_b.headers,
    )
    assert via_query.status_code == 201
    assert [e["reason"] for e in _audit(clinic_b.tenant_id)][-2:] == [
        "CLIENT_TENANT_ID_IGNORED",
        None,
    ]


def test_other_unknown_fields_are_422(rbac: RbacApi, outbox: Outbox) -> None:
    owner = rbac.register_tenant(clinic_name="Strict Body Clinic")
    for extra in (
        {"password": "chosen-by-admin"},
        {"granted_by": str(owner.user_id)},
        {"is_superuser": True},
    ):
        body = _invite_body(rbac, owner, "NURSE") | extra
        response = rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
        assert response.status_code == 422, extra
        assert _account(body["email"]) is None
    empty_roles = _invite_body(rbac, owner, "NURSE") | {"role_ids": []}
    assert (
        rbac.client.post(STAFF_URL, json=empty_roles, headers=owner.headers).status_code
        == 422
    )
    assert outbox.sent == []


def test_a_role_beyond_the_callers_own_is_refused_403(
    rbac: RbacApi, outbox: Outbox
) -> None:
    owner = rbac.register_tenant(clinic_name="Escalation Clinic")
    assert owner.tenant_id is not None
    admin = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="ADMINISTRATOR"
    )
    for code in ("PRACTICE_OWNER", "DOCTOR"):
        body = _invite_body(rbac, owner, code)
        refused = rbac.client.post(STAFF_URL, json=body, headers=admin.headers)
        assert refused.status_code == 403, code
        assert _code(refused) == "GRANT_EXCEEDS_ACTOR"
        assert _account(body["email"]) is None
    # One grantable role does not carry a second, ungrantable one in with it.
    mixed = _invite_body(rbac, owner, "ADMINISTRATOR", "PRACTICE_OWNER")
    assert (
        rbac.client.post(STAFF_URL, json=mixed, headers=admin.headers).status_code
        == 403
    )
    assert _account(mixed["email"]) is None
    assert outbox.sent == []

    events = _audit(owner.tenant_id)
    assert [(e["result"], e["reason"]) for e in events] == [
        ("DENIED", "GRANT_EXCEEDS_ACTOR")
    ] * 3
    assert events[0]["payload"] == {"added": ["PRACTICE_OWNER"], "step_up": False}

    # What the administrator does hold, they may grant.
    allowed = rbac.client.post(
        STAFF_URL,
        json=_invite_body(rbac, owner, "ADMINISTRATOR"),
        headers=admin.headers,
    )
    assert allowed.status_code == 201, allowed.text


def test_a_taken_address_gets_one_answer_whichever_tenant_holds_it(
    rbac: RbacApi, outbox: Outbox
) -> None:
    clinic_a = rbac.register_tenant(clinic_name="Duplicate Clinic A")
    clinic_b = rbac.register_tenant(clinic_name="Duplicate Clinic B")
    assert clinic_a.tenant_id is not None
    a_doctor = rbac.add_actor(tenant_id=clinic_a.tenant_id, granted_by=clinic_a.user_id)

    own = rbac.client.post(
        STAFF_URL,
        json=_invite_body(rbac, clinic_b, "NURSE", email=clinic_b.email),
        headers=clinic_b.headers,
    )
    other = rbac.client.post(
        STAFF_URL,
        json=_invite_body(rbac, clinic_b, "NURSE", email=a_doctor.email.upper()),
        headers=clinic_b.headers,
    )
    for response in (own, other):
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "EMAIL_UNAVAILABLE",
            "message": "This email address can't be invited. It may already have an account.",
        }
    assert _account(a_doctor.email)["tenant_id"] == clinic_a.tenant_id  # type: ignore[index]
    assert outbox.sent == []
    assert [(e["result"], e["reason"]) for e in _audit(clinic_b.tenant_id)] == [
        ("DENIED", "EMAIL_UNAVAILABLE")
    ] * 2
    assert _audit(clinic_a.tenant_id) == [], (
        "the refusal says nothing to the holding tenant"
    )


def test_a_concurrent_duplicate_is_still_409(rbac: RbacApi, outbox: Outbox) -> None:
    """The unique index is the last word: a race past the check rolls back and answers `409`."""
    owner = rbac.register_tenant(clinic_name="Race Clinic")
    body = _invite_body(rbac, owner, "NURSE", email=owner.email)
    with patch.object(service, "_email_taken", return_value=False):
        response = rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
    assert response.status_code == 409
    assert _code(response) == "EMAIL_UNAVAILABLE"
    assert outbox.sent == []


def test_no_outgoing_mail_is_503_and_creates_nothing(
    rbac: RbacApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = rbac.register_tenant(clinic_name="No Mail Clinic")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    body = _invite_body(rbac, owner, "NURSE")
    response = rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
    assert response.status_code == 503
    assert _code(response) == "EMAIL_NOT_CONFIGURED"
    assert _account(body["email"]) is None


def test_a_failed_audit_write_or_email_creates_nothing(
    rbac: RbacApi, outbox: Outbox
) -> None:
    """INV-4: the account, its grants, its events and its email are one unit."""
    owner = rbac.register_tenant(clinic_name="Atomic Clinic")
    assert owner.tenant_id is not None
    real_record = service.audit.record

    def refuse_create(session: Any, event: Any) -> Any:
        if event.action == "user.create" and event.result == "SUCCESS":
            raise service.audit.AuditWriteRefused("simulated")
        return real_record(session, event)

    body = _invite_body(rbac, owner, "NURSE")
    with (
        patch.object(service.audit, "record", side_effect=refuse_create),
        pytest.raises(service.audit.AuditWriteRefused),
    ):
        rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
    assert _account(body["email"]) is None
    assert outbox.sent == []

    failing = _invite_body(rbac, owner, "NURSE")
    with (
        patch("app.utils.send_email", side_effect=ConnectionError("smtp down")),
        pytest.raises(ConnectionError),
    ):
        rbac.client.post(STAFF_URL, json=failing, headers=owner.headers)
    assert _account(failing["email"]) is None
    assert _audit(owner.tenant_id) == [], (
        "a rolled-back invitation left an event behind"
    )


# --- Success path ------------------------------------------------------------------------------


def test_an_invited_person_sets_a_password_once_and_lands_in_the_right_tenant(
    rbac: RbacApi, outbox: Outbox
) -> None:
    owner = rbac.register_tenant(clinic_name="Onboarding Clinic")
    assert owner.tenant_id is not None
    body = _invite_body(rbac, owner, "DOCTOR", "NURSE")
    body["email"] = body["email"].replace("staff-", "New.Staff-")

    created = rbac.client.post(STAFF_URL, json=body, headers=owner.headers)
    assert created.status_code == 201, created.text
    member = created.json()
    assert member["full_name"] == "Dana Staff"
    assert member["is_active"] is True
    assert [role["code"] for role in member["roles"]] == ["DOCTOR", "NURSE"]
    assert "tenant_id" not in member and "hashed_password" not in member

    # The directory lists the new account with its roles.
    listed = rbac.client.get(STAFF_URL, headers=owner.headers).json()
    assert listed["count"] == 2
    assert {m["id"] for m in listed["data"]} == {str(owner.user_id), member["id"]}

    # The audit trail: who was created, with which roles, by whom, and each grant.
    (created_event,) = _audit(owner.tenant_id)
    assert created_event["result"] == "SUCCESS"
    assert created_event["actor_id"] == owner.user_id
    assert str(created_event["resource_id"]) == member["id"]
    assert created_event["payload"] == {
        "target_user_id": member["id"],
        "added": ["DOCTOR", "NURSE"],
        "step_up": False,
    }
    grants = [
        e
        for e in _audit(owner.tenant_id, "user.permission_change")
        if e["payload"]["target_user_id"] == member["id"]
    ]
    assert [(g["payload"]["role_code"], g["payload"]["change"]) for g in grants] == [
        ("DOCTOR", "GRANT"),
        ("NURSE", "GRANT"),
    ]
    assert {g["request_id"] for g in grants} == {created_event["request_id"]}

    # Exactly one email, to the invitee, naming the clinic, linking to the app's accept page.
    (message,) = outbox.sent
    assert message["email_to"] == body["email"]
    assert "Onboarding Clinic" in message["subject"]
    assert f"{settings.FRONTEND_HOST}/accept-invite?token=" in message["html_content"]
    token = outbox.token_for(body["email"])

    # Nobody can sign in before the invitee chooses a password; the admin never knew one.
    before = rbac.client.post(
        LOGIN_URL, data={"username": body["email"], "password": NEW_PASSWORD}
    )
    assert before.status_code == 400

    accepted = rbac.client.post(
        ACCEPT_URL, json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"email": body["email"]}

    # Single use.
    again = rbac.client.post(
        ACCEPT_URL, json={"token": token, "new_password": "another-passphrase"}
    )
    assert again.status_code == 400
    assert _code(again) == "INVITATION_INVALID"

    signed_in = rbac.client.post(
        LOGIN_URL, data={"username": body["email"], "password": NEW_PASSWORD}
    )
    assert signed_in.status_code == 200
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    me = rbac.client.get(f"{API}/users/me", headers=headers).json()
    assert me["tenant_id"] == str(owner.tenant_id)
    assert me["is_superuser"] is False
    permissions = rbac.client.get(f"{API}/users/me/permissions", headers=headers).json()
    assert permissions["permissions"] == sorted(
        set(BUNDLES["DOCTOR"]) | set(BUNDLES["NURSE"])
    )
    # And, holding no `users:manage`, the new doctor cannot list the staff.
    assert rbac.client.get(STAFF_URL, headers=headers).status_code == 403


@pytest.mark.usefixtures("outbox")
def test_the_list_pages_and_bounds_its_size(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Paging Clinic")
    for name in ("Avery", "blake", "Casey"):
        body = _invite_body(rbac, owner, "NURSE") | {"full_name": name}
        assert (
            rbac.client.post(STAFF_URL, json=body, headers=owner.headers).status_code
            == 201
        )

    first = rbac.client.get(
        STAFF_URL, params={"limit": 2}, headers=owner.headers
    ).json()
    second = rbac.client.get(
        STAFF_URL, params={"limit": 2, "skip": 2}, headers=owner.headers
    ).json()
    assert first["count"] == second["count"] == 4
    names = [m["full_name"] for m in first["data"] + second["data"]]
    assert names == ["Avery", "blake", "Casey", "Practice Owner"]
    beyond = rbac.client.get(STAFF_URL, params={"skip": 10}, headers=owner.headers)
    assert beyond.json() == {"data": [], "count": 4}
    assert (
        rbac.client.get(
            STAFF_URL, params={"limit": 101}, headers=owner.headers
        ).status_code
        == 422
    )
    assert (
        rbac.client.get(
            STAFF_URL, params={"skip": -1}, headers=owner.headers
        ).status_code
        == 422
    )


# --- The invitation link -----------------------------------------------------------------------


def _invited(
    rbac: RbacApi, outbox: Outbox, clinic: str
) -> tuple[ActorSession, str, str]:
    owner = rbac.register_tenant(clinic_name=clinic)
    body = _invite_body(rbac, owner, "NURSE")
    assert (
        rbac.client.post(STAFF_URL, json=body, headers=owner.headers).status_code == 201
    )
    return owner, body["email"], outbox.token_for(body["email"])


def test_a_tampered_expired_or_foreign_token_is_refused(
    rbac: RbacApi, outbox: Outbox
) -> None:
    _owner, email, token = _invited(rbac, outbox, "Token Clinic")
    account = _account(email)
    assert account is not None
    with engine.connect() as conn:
        hashed = conn.execute(
            text('SELECT hashed_password FROM "user" WHERE id = :id'),
            {"id": account["id"]},
        ).scalar_one()

    expired = invitations.issue(
        user_id=account["id"],
        hashed_password=hashed,
        now=datetime.now(UTC)
        - timedelta(hours=settings.STAFF_INVITATION_EXPIRE_HOURS + 1),
    )
    access_token = create_access_token(str(account["id"]), timedelta(minutes=5))
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[::-1]}"
    other_purpose = jwt.encode(
        {
            "sub": str(account["id"]),
            "purpose": "password-reset",
            "pwd": invitations.fingerprint(hashed),
            "nbf": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        invitations._key(),
        algorithm="HS256",
    )
    for bad in (expired, access_token, tampered, other_purpose, "not-a-token"):
        response = rbac.client.post(
            ACCEPT_URL, json={"token": bad, "new_password": NEW_PASSWORD}
        )
        assert response.status_code == 400, bad
        assert _code(response) == "INVITATION_INVALID"

    # The invitation token is not a session either.
    assert (
        rbac.client.get(
            f"{API}/users/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    # The real link still works after all those refusals (in a fresh rate-limit window).
    limiter.clear()
    assert (
        rbac.client.post(
            ACCEPT_URL, json={"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_a_password_set_another_way_retires_the_link(
    rbac: RbacApi, outbox: Outbox
) -> None:
    _owner, email, token = _invited(rbac, outbox, "Recovery Clinic")
    account = _account(email)
    assert account is not None
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE "user" SET hashed_password = :h WHERE id = :id'),
            {"h": invitations.unusable_password_hash(), "id": account["id"]},
        )
    response = rbac.client.post(
        ACCEPT_URL, json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 400


def test_a_deactivated_or_missing_account_cannot_accept(
    rbac: RbacApi, outbox: Outbox
) -> None:
    _owner, email, token = _invited(rbac, outbox, "Deactivated Clinic")
    account = _account(email)
    assert account is not None
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE "user" SET is_active = false WHERE id = :id'),
            {"id": account["id"]},
        )
    assert (
        rbac.client.post(
            ACCEPT_URL, json={"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 400
    )

    ghost = invitations.issue(user_id=uuid.uuid4(), hashed_password="x")
    assert (
        rbac.client.post(
            ACCEPT_URL, json={"token": ghost, "new_password": NEW_PASSWORD}
        ).status_code
        == 400
    )


def test_accepting_is_rate_limited(client: TestClient) -> None:
    statuses = [
        client.post(
            ACCEPT_URL, json={"token": "guess", "new_password": NEW_PASSWORD}
        ).status_code
        for _ in range(6)
    ]
    assert statuses == [400] * 5 + [429]


def test_the_staff_route_is_not_captured_as_an_account_id(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """Mounted before the legacy `/users/{user_id}`: `staff` must never be parsed as a UUID (`422`)."""
    response = client.get(STAFF_URL, headers=superuser_token_headers)
    assert response.status_code == 403
    assert _code(response) == "NO_ORGANISATION"
