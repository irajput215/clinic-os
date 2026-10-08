"""The clinic display name: `GET`/`PATCH /api/v1/tenants/current/profile` and `GET /public/{slug}`.

Contract: `docs2/sdlc/01-auth-and-shell/api.md`, "Clinic display name". The display name is PUBLIC;
`legal_name` stays CONFIDENTIAL and never reaches any of these routes. Renaming needs
`tenant:configure` (Practice Owner), and every refusal and every change is audited
`tenant.config_changed` on the transaction that decided it.

Denial paths first (`docs/reference/definition-of-done.md` §9), then validation, then success.
"""

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.modules.identity_tenancy import service as identity_service
from app.modules.identity_tenancy.models import DISPLAY_NAME_MAX_LENGTH
from app.modules.identity_tenancy.schemas import normalise_display_name
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
PROFILE_URL = f"{API}/tenants/current/profile"
ACTION = "tenant.config_changed"


def _public(slug: str) -> str:
    return f"{API}/public/{slug}"


def _tenant_row(tenant_id: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT slug, legal_name, display_name, updated_at FROM tenants"
                    " WHERE id = :id"
                ),
                {"id": tenant_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def _audit(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """The tenant's `tenant.config_changed` events, oldest first, read as the owner."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT result, reason, actor_id, resource_id, resource_type,"
                " metadata AS payload FROM audit_log"
                " WHERE tenant_id = :tenant_id AND action = :action"
                " ORDER BY timestamp, event_id"
            ),
            {"tenant_id": tenant_id, "action": ACTION},
        ).mappings()
        return [dict(row) for row in rows]


def _owner(rbac: RbacApi, clinic_name: str) -> ActorSession:
    owner = rbac.register_tenant(clinic_name=clinic_name)
    assert owner.tenant_id is not None
    return owner


def _code(response: Any) -> str:
    return str(response.json()["detail"]["code"])


# --- Denial path -------------------------------------------------------------------------------


def test_no_session_is_401(rbac: RbacApi) -> None:
    assert rbac.client.get(PROFILE_URL).status_code == 401
    assert rbac.client.patch(PROFILE_URL, json={"display_name": "X"}).status_code == 401


def test_an_account_with_no_organisation_is_refused(rbac: RbacApi) -> None:
    loner = rbac.register_tenant(clinic_name=None)
    for response in (
        rbac.client.get(PROFILE_URL, headers=loner.headers),
        rbac.client.patch(
            PROFILE_URL, json={"display_name": "Mine now"}, headers=loner.headers
        ),
    ):
        assert response.status_code == 403
        assert _code(response) == "NO_ORGANISATION"


@pytest.mark.parametrize(
    "role_code",
    ["ADMINISTRATOR", "DOCTOR", "NURSE", "COMPLIANCE_AUDITOR", "PHARMACY"],
)
def test_a_role_without_tenant_configure_is_403_audited_and_changes_nothing(
    rbac: RbacApi, role_code: str
) -> None:
    owner = _owner(rbac, "Denied Rename Clinic")
    assert owner.tenant_id is not None
    member = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code=role_code
    )
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(
        PROFILE_URL, json={"display_name": "Hijacked"}, headers=member.headers
    )

    assert response.status_code == 403, response.text
    assert _code(response) == "PERMISSION_NOT_HELD"
    assert _tenant_row(owner.tenant_id) == before
    (event,) = _audit(owner.tenant_id)
    assert (event["result"], event["reason"]) == ("DENIED", "PERMISSION_NOT_HELD")
    assert event["actor_id"] == member.user_id
    assert event["resource_type"] == "TENANT"
    assert event["resource_id"] == owner.tenant_id
    assert event["payload"] == {"changed_fields": ["display_name"], "step_up": False}


def test_a_refusal_that_cannot_be_audited_fails_closed(rbac: RbacApi) -> None:
    """INV-4: no silent `403` - an unrecordable refusal is an error, and still changes nothing."""
    owner = _owner(rbac, "Unaudited Refusal Clinic")
    assert owner.tenant_id is not None
    doctor = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="DOCTOR"
    )
    before = _tenant_row(owner.tenant_id)

    with (
        patch.object(
            identity_service.audit,
            "record",
            side_effect=identity_service.audit.AuditWriteRefused("simulated"),
        ),
        pytest.raises(identity_service.audit.AuditWriteRefused),
    ):
        rbac.client.patch(
            PROFILE_URL, json={"display_name": "Hijacked"}, headers=doctor.headers
        )
    assert _tenant_row(owner.tenant_id) == before


def test_another_tenant_cannot_be_renamed_by_construction(rbac: RbacApi) -> None:
    """INV-1: no tenant identifier is read. A body, query or header `tenant_id` naming another
    organisation is ignored, the caller's own clinic is the one renamed, and the attempt is audited
    on the caller's trail. The other organisation's row and trail are untouched."""
    alpha = _owner(rbac, "Alpha Rename Clinic")
    beta = _owner(rbac, "Beta Rename Clinic")
    assert alpha.tenant_id is not None and beta.tenant_id is not None
    beta_before = _tenant_row(beta.tenant_id)

    response = rbac.client.patch(
        f"{PROFILE_URL}?tenant_id={beta.tenant_id}",
        json={"display_name": "Alpha Renamed", "tenant_id": str(beta.tenant_id)},
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"display_name": "Alpha Renamed"}
    assert _tenant_row(alpha.tenant_id)["display_name"] == "Alpha Renamed"
    assert _tenant_row(beta.tenant_id) == beta_before
    assert [(e["result"], e["reason"]) for e in _audit(alpha.tenant_id)] == [
        ("DENIED", "CLIENT_TENANT_ID_IGNORED"),
        ("SUCCESS", None),
    ]
    assert _audit(beta.tenant_id) == []


def test_the_public_page_never_exposes_legal_name(rbac: RbacApi) -> None:
    owner = _owner(rbac, "Confidential Legal Entity Pty Ltd")
    assert owner.tenant_id is not None
    row = _tenant_row(owner.tenant_id)

    response = rbac.client.get(_public(row["slug"]))

    assert response.status_code == 200, response.text
    assert response.json() == {"display_name": row["display_name"]}

    # Renamed, the public name changes and the legal name still appears nowhere.
    renamed = rbac.client.patch(
        PROFILE_URL, json={"display_name": "Friendly Clinic"}, headers=owner.headers
    )
    assert renamed.status_code == 200, renamed.text
    public = rbac.client.get(_public(row["slug"]))
    assert public.json() == {"display_name": "Friendly Clinic"}
    assert "Pty Ltd" not in public.text
    assert str(owner.tenant_id) not in public.text
    # Nor does any member-facing read carry it.
    profile = rbac.client.get(PROFILE_URL, headers=owner.headers)
    assert "Pty Ltd" not in profile.text
    current = rbac.client.get(f"{API}/tenants/current", headers=owner.headers)
    assert "Pty Ltd" not in current.text


def test_the_public_page_answers_one_404_for_unknown_malformed_and_inactive(
    rbac: RbacApi,
) -> None:
    owner = _owner(rbac, "Suspended Public Clinic")
    assert owner.tenant_id is not None
    slug = _tenant_row(owner.tenant_id)["slug"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tenants SET status = 'SUSPENDED' WHERE id = :id"),
            {"id": owner.tenant_id},
        )

    answers = [
        rbac.client.get(_public(candidate))
        for candidate in (slug, f"no-such-{uuid.uuid4().hex[:8]}", "Not_A_Slug")
    ]

    assert [a.status_code for a in answers] == [404, 404, 404]
    assert len({str(a.json()["detail"]) for a in answers}) == 1
    assert _code(answers[0]) == "CLINIC_NOT_FOUND"


# --- Validation --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "\t\n",
        "x" * (DISPLAY_NAME_MAX_LENGTH + 1),
        "Clinic\x00Name",
        "Clinic\x07",
        # A right-to-left override would make the public page read differently from what was typed.
        "Clinic ‮evil",
        "Zero​Width",
    ],
)
def test_an_invalid_name_is_422_and_changes_nothing(rbac: RbacApi, value: str) -> None:
    owner = _owner(rbac, "Validation Clinic")
    assert owner.tenant_id is not None
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(
        PROFILE_URL, json={"display_name": value}, headers=owner.headers
    )

    assert response.status_code == 422, response.text
    assert _tenant_row(owner.tenant_id) == before
    assert _audit(owner.tenant_id) == []


@pytest.mark.parametrize(
    "body",
    [{}, {"display_name": None}, {"display_name": 42}, {"display_name": "Ok", "x": 1}],
)
def test_a_malformed_body_is_422(rbac: RbacApi, body: dict[str, Any]) -> None:
    owner = _owner(rbac, "Malformed Body Clinic")
    response = rbac.client.patch(PROFILE_URL, json=body, headers=owner.headers)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("  Green   Valley\tClinic  ", "Green Valley Clinic"),
        ("Dr Ng's Clinic & Co.", "Dr Ng's Clinic & Co."),
        ("Clínica São José", "Clínica São José"),
        ("x" * DISPLAY_NAME_MAX_LENGTH, "x" * DISPLAY_NAME_MAX_LENGTH),
    ],
)
def test_names_are_trimmed_and_collapsed(typed: str, stored: str) -> None:
    assert normalise_display_name(typed) == stored


def test_the_database_refuses_what_the_api_refuses(rbac: RbacApi) -> None:
    """`ck_tenants_display_name` is the last line: a writer that skipped the schema is refused."""
    owner = _owner(rbac, "Constraint Clinic")
    assert owner.tenant_id is not None
    for bad in ("", " padded", "padded ", "bell\x07"):
        with pytest.raises(IntegrityError, match="ck_tenants_display_name"):
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE tenants SET display_name = :v WHERE id = :id"),
                    {"v": bad, "id": owner.tenant_id},
                )
    with pytest.raises(DataError, match="too long"):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE tenants SET display_name = :v WHERE id = :id"),
                {"v": "x" * (DISPLAY_NAME_MAX_LENGTH + 1), "id": owner.tenant_id},
            )


# --- Success -----------------------------------------------------------------------------------


def test_the_owner_renames_and_every_member_sees_it(rbac: RbacApi) -> None:
    owner = _owner(rbac, "Before Rename Clinic")
    assert owner.tenant_id is not None
    nurse = rbac.add_actor(
        tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="NURSE"
    )
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(
        PROFILE_URL,
        json={"display_name": "  After   Rename Clinic "},
        headers=owner.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"display_name": "After Rename Clinic"}
    after = _tenant_row(owner.tenant_id)
    assert after["display_name"] == "After Rename Clinic"
    assert after["legal_name"] == before["legal_name"], "the legal name is not touched"
    assert after["slug"] == before["slug"], "the booking link does not move"
    assert after["updated_at"] > before["updated_at"]
    # A member without `tenant:configure` reads the name (it is PUBLIC) but cannot change it.
    read = rbac.client.get(PROFILE_URL, headers=nurse.headers)
    assert read.status_code == 200, read.text
    assert read.json() == {"display_name": "After Rename Clinic"}

    (event,) = _audit(owner.tenant_id)
    assert (event["result"], event["reason"]) == ("SUCCESS", None)
    assert event["actor_id"] == owner.user_id
    assert event["resource_id"] == owner.tenant_id
    # Field names only: the name itself is never in the trail.
    assert event["payload"] == {"changed_fields": ["display_name"], "step_up": False}


def test_saving_the_same_name_writes_and_records_nothing(rbac: RbacApi) -> None:
    owner = _owner(rbac, "Same Name Clinic")
    assert owner.tenant_id is not None
    before = _tenant_row(owner.tenant_id)

    response = rbac.client.patch(
        PROFILE_URL,
        json={"display_name": before["display_name"]},
        headers=owner.headers,
    )

    assert response.status_code == 200, response.text
    assert _tenant_row(owner.tenant_id) == before
    assert _audit(owner.tenant_id) == []


def test_the_rename_and_its_event_are_one_transaction(rbac: RbacApi) -> None:
    """INV-4: a failed audit write rolls the rename back."""
    owner = _owner(rbac, "Atomic Rename Clinic")
    assert owner.tenant_id is not None
    before = _tenant_row(owner.tenant_id)

    with (
        patch.object(
            identity_service.audit,
            "record",
            side_effect=identity_service.audit.AuditWriteRefused("simulated"),
        ),
        pytest.raises(identity_service.audit.AuditWriteRefused),
    ):
        rbac.client.patch(
            PROFILE_URL, json={"display_name": "Never Saved"}, headers=owner.headers
        )

    assert _tenant_row(owner.tenant_id) == before
    assert _audit(owner.tenant_id) == []


# --- Signup and the other readers ----------------------------------------------------------------


def test_signup_sets_the_display_name_from_the_clinic_name(rbac: RbacApi) -> None:
    owner = _owner(rbac, "  Harbour   View Medical  ")
    assert owner.tenant_id is not None
    row = _tenant_row(owner.tenant_id)
    assert row["display_name"] == "Harbour View Medical"
    assert row["legal_name"] == "  Harbour   View Medical  ", (
        "the legal name is kept as typed"
    )


def test_a_signup_name_longer_than_the_display_name_is_cut_at_a_word() -> None:
    long_name = "Northern Beaches " * 14  # 238 characters
    name = identity_service.signup_display_name(long_name, slug="northern-beaches")
    assert len(name) <= DISPLAY_NAME_MAX_LENGTH
    assert long_name.startswith(name)
    assert name.endswith("Beaches")


@pytest.mark.parametrize(
    ("clinic_name", "slug", "expected"),
    [
        ("\x00\x01", "organisation", "Organisation"),
        ("Bad\x07Bell Clinic", "bad-bell-clinic", "Bad Bell Clinic"),
        ("y" * 200, "yyy", "y" * DISPLAY_NAME_MAX_LENGTH),
    ],
)
def test_a_signup_name_that_cannot_be_used_as_is_still_gives_a_valid_name(
    clinic_name: str, slug: str, expected: str
) -> None:
    name = identity_service.signup_display_name(clinic_name, slug=slug)
    assert name == expected
    assert normalise_display_name(name) == name


def test_display_name_from_slug() -> None:
    assert identity_service.display_name_from_slug("green-valley-2") == "Green Valley 2"
    assert identity_service.display_name_from_slug("-") == "Clinic"


def test_the_organisation_name_in_staff_emails_is_the_display_name(
    rbac: RbacApi,
) -> None:
    """The staff invitation names the clinic: its PUBLIC name, never the CONFIDENTIAL legal one."""
    owner = _owner(rbac, "Invite Legal Entity Pty Ltd")
    assert owner.tenant_id is not None
    rbac.client.patch(
        PROFILE_URL, json={"display_name": "Invite Clinic"}, headers=owner.headers
    )
    with Session(engine) as session:
        assert (
            identity_service.tenant_display_name(session, tenant_id=owner.tenant_id)
            == "Invite Clinic"
        )
