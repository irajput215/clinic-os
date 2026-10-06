"""T1-09 — the permission catalogue and the seven system role bundles.

The catalogue is the 19 codes in `docs/features/03-users-and-roles/01-requirements.md` "Permission
catalogue (role x permission)", and each role's resolved set is the `G` cells of that matrix. **OPEN-1**
is still open, so this asserts the 19-code transcription the seed was built from, not a settled
catalogue; a change to the matrix must change `catalog.py` and this test together.

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
# while OPEN-1 is open, so none may appear in the seeded catalogue.
CANDIDATE_CODES = (
    "tenant:read",
    "clinic:manage",
    "patient:merge",
    "clinical_record:create",
    "admin:feature_flag",
    "export:bulk",
)


def _stored_permission_codes(tenant_id: uuid.UUID) -> set[str]:
    with tenant_transaction(tenant_id=tenant_id) as session:
        stored = session.exec(select(Permission)).all()
        return {permission.code for permission in stored}


def test_the_permission_catalogue_is_the_declared_codes(rbac: RbacApi) -> None:
    """The catalogue as `catalog.py` declares it, which is 19 + Feature 08's `tga_approval:revoke`.

    Feature 08's endpoints table requires a `tga_approval:revoke` permission
    (`docs/features/08-tga-approvals/03-design.md`), and the alternative — reusing
    `tga_approval:verify` — would let a `COMPLIANCE_AUDITOR` revoke an approval, which that feature's
    US-7 forbids. This test's own docstring is the rule it follows here: *"a change to the matrix
    must change `catalog.py` and this test together"*.
    """
    owner = rbac.register_tenant(clinic_name="Catalogue Clinic")
    assert owner.tenant_id is not None
    stored = _stored_permission_codes(owner.tenant_id)
    assert len(PERMISSION_CATALOGUE) == 20
    assert stored == PERMISSION_CODES
    assert len(stored) == 20


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
