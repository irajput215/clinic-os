"""T1-09 — the permission catalogue and the seven system role bundles.

The catalogue is the 19 codes in `docs/features/03-users-and-roles/01-requirements.md` "Permission
catalogue (role x permission)", and each role's resolved set is the `G` cells of that matrix. **OPEN-1**
is still open, so this asserts the 19-code transcription the seed was built from, not a settled
catalogue; a change to the matrix must change `catalog.py` and this test together.

**Two codes have been added since, and each is a named deviation rather than a silent drift from
nineteen**: `tenant:read`, which `docs/features/01-tenancy-and-clinics/03-design.md` "Endpoints"
requires for `GET /api/v1/tenants/current` and records as OPEN-2 ("absent from the fixed
19-permission catalogue"); and `tga_approval:revoke`, which
`docs/features/08-tga-approvals/03-design.md` "Endpoints" requires for the revoke route, and which is
deliberately **not** satisfied by reusing `tga_approval:verify` — that would let a
`COMPLIANCE_AUDITOR` revoke an approval, which Feature 08's US-7 forbids. Both are named in
`ADDED_CODES` below and asserted separately.

A `tenant_transaction` expires its ORM attributes at COMMIT, so every value is read inside the block.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.db import tenant_transaction
from app.modules.users_roles.catalog import (
    PERMISSION_CATALOGUE,
    PERMISSION_CODES,
    SYSTEM_ROLE_CATALOGUE,
)
from app.modules.users_roles.models import Permission, Role
from app.modules.users_roles.service import actor_for, seed_tenant_roles
from tests.utils.rbac import RbacApi

# Codes named by `01-requirements.md` under "Candidate additions named elsewhere". None is granted
# while OPEN-1 is open, so none may appear in the seeded catalogue. `tenant:read` was on that list and
# has been promoted by the Feature 01 tenancy routes (OPEN-2); it is asserted in `ADDED_CODES` below
# instead, so this tuple keeps meaning "not granted".
CANDIDATE_CODES = (
    "clinic:manage",
    "patient:merge",
    "clinical_record:create",
    "admin:feature_flag",
    "export:bulk",
)

# The seeded codes that are **not** in the 19 of `01-requirements.md`, with the route that needs each.
# Two names now stand here, and each is a permission-matrix change and needs the CTO's OPEN-1/OPEN-2
# reconciliation: `tenant:read` (Feature 01's `GET /api/v1/tenants/current`) and `tga_approval:revoke`
# (Feature 08's `POST /api/v1/tga-approvals/{id}/revoke`).
ADDED_CODES = ("tenant:read", "tga_approval:revoke")


def _stored_permission_codes(tenant_id: uuid.UUID) -> set[str]:
    with tenant_transaction(tenant_id=tenant_id) as session:
        stored = session.exec(select(Permission)).all()
        return {permission.code for permission in stored}


def test_the_permission_catalogue_is_the_declared_codes(rbac: RbacApi) -> None:
    """The seeded catalogue is the 19 codes of the matrix plus the recorded additions, and nothing else.

    The count assertion is deliberate rather than derived from `PERMISSION_CATALOGUE`: a test that
    reads its expected value from the thing it is testing cannot fail. `ADDED_CODES` names the
    deviations here, so a reader sees them in the test that guards the matrix instead of inferring
    them from a diff.
    """
    owner = rbac.register_tenant(clinic_name="Catalogue Clinic")
    assert owner.tenant_id is not None
    stored = _stored_permission_codes(owner.tenant_id)
    assert len(PERMISSION_CATALOGUE) == 19 + len(ADDED_CODES)
    assert stored == PERMISSION_CODES
    assert len(stored) == 19 + len(ADDED_CODES)


@pytest.mark.parametrize("code", ADDED_CODES)
def test_an_added_code_is_seeded_and_granted(rbac: RbacApi, code: str) -> None:
    """The addition is real: the row is seeded, and the code resolves for every role that holds it.

    The roles are read from `SYSTEM_ROLE_CATALOGUE`, not written down. `tenant:read` is held by
    `PRACTICE_OWNER` and `COMPLIANCE_AUDITOR`; `tga_approval:revoke` by `PRACTICE_OWNER` alone — which
    is the whole point of adding it, because a `COMPLIANCE_AUDITOR` who could revoke is exactly what
    Feature 08's US-7 forbids. A hardcoded `COMPLIANCE_AUDITOR` here would assert the opposite of the
    requirement for the second code.
    """
    owner = rbac.register_tenant(clinic_name="Catalogue Clinic")
    assert owner.tenant_id is not None
    assert code in _stored_permission_codes(owner.tenant_id)

    holders = [role for role, _name, bundle in SYSTEM_ROLE_CATALOGUE if code in bundle]
    assert holders, (
        f"{code} is seeded but no system role holds it, so no route can ever resolve it"
    )
    for role_code in holders:
        holder = rbac.add_actor(
            tenant_id=owner.tenant_id,
            granted_by=owner.user_id,
            role_code=role_code,
        )
        resolved = actor_for(
            user_id=holder.user_id,
            tenant_id=owner.tenant_id,
            is_active=True,
        )
        assert code in resolved.permissions, role_code


@pytest.mark.parametrize("code", CANDIDATE_CODES)
def test_a_candidate_code_is_not_granted(rbac: RbacApi, code: str) -> None:
    owner = rbac.register_tenant(clinic_name="Catalogue Clinic")
    assert owner.tenant_id is not None
    assert code not in _stored_permission_codes(owner.tenant_id)


def test_each_role_resolves_to_its_declared_permission_set(rbac: RbacApi) -> None:
    """The seed assertion T1-09 names: every cell is an explicit grant or denial."""
    owner = rbac.register_tenant(clinic_name="Bundle Clinic")
    assert owner.tenant_id is not None

    for code, name, bundle in SYSTEM_ROLE_CATALOGUE:
        actor = rbac.add_actor(
            tenant_id=owner.tenant_id,
            granted_by=owner.user_id,
            role_code=code,
        )
        resolved = actor_for(
            user_id=actor.user_id,
            tenant_id=owner.tenant_id,
            is_active=True,
        )
        assert resolved.permissions == bundle, (
            f"{code} ({name}) resolved to {sorted(resolved.permissions)}, "
            f"the design's bundle is {sorted(bundle)}"
        )


def test_each_tenant_gets_exactly_the_seven_system_roles(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Seven Roles Clinic")
    assert owner.tenant_id is not None
    with tenant_transaction(tenant_id=owner.tenant_id) as session:
        roles = session.exec(
            select(Role).where(Role.tenant_id == owner.tenant_id)
        ).all()
        codes = {role.code for role in roles}
        all_system = all(role.is_system for role in roles)
    assert codes == {code for code, _, _ in SYSTEM_ROLE_CATALOGUE}
    assert all_system


def test_the_seed_is_idempotent(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Idempotent Clinic")
    assert owner.tenant_id is not None
    with tenant_transaction(tenant_id=owner.tenant_id) as session:
        seed_tenant_roles(session, tenant_id=owner.tenant_id)
        seed_tenant_roles(session, tenant_id=owner.tenant_id)
    with tenant_transaction(tenant_id=owner.tenant_id) as session:
        count = len(
            session.exec(select(Role).where(Role.tenant_id == owner.tenant_id)).all()
        )
    assert count == 7


def test_a_role_code_outside_the_seven_is_refused(rbac: RbacApi) -> None:
    """R7/T-03.9: a tenant may rename a role; it may not invent a code while OPEN-2 is open."""
    owner = rbac.register_tenant(clinic_name="Invented Role Clinic")
    assert owner.tenant_id is not None
    with pytest.raises(IntegrityError, match="ck_roles_code"):
        with tenant_transaction(tenant_id=owner.tenant_id) as session:
            session.add(
                Role(
                    tenant_id=owner.tenant_id,
                    code="SUPERUSER",
                    name="Superuser",
                    is_system=False,
                )
            )


def test_the_role_display_name_may_differ_from_the_code(rbac: RbacApi) -> None:
    owner = rbac.register_tenant(clinic_name="Rename Clinic")
    assert owner.tenant_id is not None
    with tenant_transaction(tenant_id=owner.tenant_id) as session:
        role = session.exec(
            select(Role).where(Role.tenant_id == owner.tenant_id, Role.code == "DOCTOR")
        ).one()
        role.name = "General Practitioner"
        session.add(role)
    with tenant_transaction(tenant_id=owner.tenant_id) as session:
        stored = session.exec(
            select(Role).where(Role.tenant_id == owner.tenant_id, Role.code == "DOCTOR")
        ).one()
        name, code = stored.name, stored.code
    assert name == "General Practitioner"
    assert code == "DOCTOR"
