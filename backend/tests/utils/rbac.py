"""Test-only helper: register organisations and act as a chosen system role.

The RBAC rows themselves are written directly, as the owner connection: a test needs an account that
holds exactly one role, and the only shipped grant path in this slice is organisation signup, which
makes the signer a Practice Owner. Nothing here is production behaviour.
"""

import uuid
from typing import Any, NamedTuple

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.models import UserCreate
from app.modules.users_roles.models import Role, UserRole

API = settings.API_V1_STR

PASSWORD = "correct-horse-battery-staple"


class ActorSession(NamedTuple):
    """One signed-in account: its organisation (None when unattached), its role and its token."""

    tenant_id: uuid.UUID | None
    user_id: uuid.UUID
    email: str
    password: str
    role_code: str | None
    headers: dict[str, str]


class RbacApi:
    """Sign up a tenant, add accounts holding one role each, and clean them all up."""

    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self._db = db
        self._tenant_ids: list[uuid.UUID] = []

    def _login(self, email: str, password: str) -> dict[str, str]:
        response = self.client.post(
            f"{API}/login/access-token",
            data={"username": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def register_tenant(self, *, clinic_name: str | None = None) -> ActorSession:
        """Register an organisation through the real signup route, then sign in as its owner."""
        email = f"rbac-{uuid.uuid4()}@example.com"
        payload: dict[str, Any] = {
            "email": email,
            "password": PASSWORD,
            "full_name": "Practice Owner",
        }
        if clinic_name is not None:
            payload["clinic_name"] = clinic_name
        created = self.client.post(f"{API}/users/signup", json=payload)
        assert created.status_code == 200, created.text
        body = created.json()
        tenant_id = uuid.UUID(body["tenant_id"]) if body["tenant_id"] else None
        if tenant_id is not None:
            self._tenant_ids.append(tenant_id)
        return ActorSession(
            tenant_id=tenant_id,
            user_id=uuid.UUID(body["id"]),
            email=email,
            password=PASSWORD,
            role_code="PRACTICE_OWNER" if tenant_id is not None else None,
            headers=self._login(email, PASSWORD),
        )

    def add_actor(
        self,
        *,
        tenant_id: uuid.UUID,
        granted_by: uuid.UUID,
        role_code: str | None = None,
    ) -> ActorSession:
        """Create an account in the tenant and optionally grant it exactly one role."""
        email = f"rbac-{uuid.uuid4()}@example.com"
        user = crud.create_user(
            session=self._db,
            user_create=UserCreate(email=email, password=PASSWORD),
        )
        user.tenant_id = tenant_id
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        if role_code is not None:
            self.grant(
                tenant_id=tenant_id,
                user_id=user.id,
                role_code=role_code,
                granted_by=granted_by,
            )
        return ActorSession(
            tenant_id=tenant_id,
            user_id=user.id,
            email=email,
            password=PASSWORD,
            role_code=role_code,
            headers=self._login(email, PASSWORD),
        )

    def grant(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role_code: str,
        granted_by: uuid.UUID,
    ) -> None:
        with tenant_transaction(tenant_id=tenant_id, actor_id=granted_by) as session:
            role = session.exec(
                select(Role).where(Role.tenant_id == tenant_id, Role.code == role_code)
            ).one()
            session.add(
                UserRole(
                    user_id=user_id,
                    role_id=role.id,
                    tenant_id=tenant_id,
                    granted_by=granted_by,
                )
            )

    def revoke_all(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM user_roles WHERE tenant_id = :tenant_id"
                    " AND user_id = :user_id"
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            )

    def patient_count(self, tenant_id: uuid.UUID) -> int:
        """Count rows as the owner, which bypasses RLS: the assertion is about rows that exist."""
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text("SELECT count(*) FROM patients WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

    def patient_row(self, patient_id: uuid.UUID) -> dict[str, Any] | None:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id, tenant_id, given_name, preferred_name, updated_at"
                        " FROM patients WHERE id = :patient_id"
                    ),
                    {"patient_id": patient_id},
                )
                .mappings()
                .first()
            )
            return None if row is None else dict(row)

    def cleanup(self) -> None:
        if not self._tenant_ids:
            return
        with engine.begin() as conn:
            for tenant_id in self._tenant_ids:
                # RESTRICT ordering: patients, then the RBAC rows, then the accounts, then the
                # organisation. Signup provisions roles and a bootstrap grant for every tenant.
                for statement in (
                    "DELETE FROM patients WHERE tenant_id = :tenant_id",
                    "DELETE FROM user_roles WHERE tenant_id = :tenant_id",
                    "DELETE FROM role_permissions WHERE tenant_id = :tenant_id",
                    "DELETE FROM roles WHERE tenant_id = :tenant_id",
                    'DELETE FROM "user" WHERE tenant_id = :tenant_id',
                    "DELETE FROM tenants WHERE id = :tenant_id",
                ):
                    conn.execute(text(statement), {"tenant_id": tenant_id})
        self._tenant_ids.clear()
