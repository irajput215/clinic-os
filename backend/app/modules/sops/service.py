"""SOPs: publish, version, read and acknowledge (docs3 feature 02, R5-R9; manual §13).

An SOP applies to the roles it names, or to everyone when it names none. A holder of
`tenant:configure` sees and edits every SOP; anyone else sees only those that apply to them, and an SOP
that does not apply is answered `404`, like another tenant's. Versions and acknowledgements are
append-only (the app role cannot update or delete them). Each publish and each acknowledgement is
audited with the version number only.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.sops.models import Sop, SopAcknowledgement, SopVersion
from app.modules.sops.schemas import (
    AcknowledgementMatrix,
    MatrixRow,
    MatrixSop,
    SopCard,
    SopDetail,
    SopVersionRead,
    SopWrite,
)
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.policy import Actor

CONFIGURE = "tenant:configure"
AUDIT_READ = "audit:read"
PUBLISH = "sop.publish"
ACKNOWLEDGE = "sop.acknowledge"
NOT_FOUND = "SOP_NOT_FOUND"
NOT_CURRENT_VERSION = "NOT_CURRENT_VERSION"


class SopRefused(Exception):  # noqa: N818 - a refusal, answered as an HTTP error by the router
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _not_found() -> SopRefused:
    return SopRefused(status.HTTP_404_NOT_FOUND, NOT_FOUND, "SOP not found")


@contextmanager
def _transaction(actor: Actor) -> Iterator[Session]:
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        yield session


def applies(sop: Sop, role_codes: frozenset[str] | set[str]) -> bool:
    """Whether `sop` applies to someone holding `role_codes` (no roles named = everyone)."""
    return not sop.applies_to_roles or bool(set(sop.applies_to_roles) & role_codes)


def _visible(actor: Actor, sop: Sop) -> bool:
    return CONFIGURE in actor.permissions or applies(sop, actor.role_codes)


def _acknowledged(
    session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    rows = session.exec(
        select(SopAcknowledgement.sop_id, func.max(SopAcknowledgement.version))
        .where(
            SopAcknowledgement.tenant_id == tenant_id,
            SopAcknowledgement.user_id == user_id,
        )
        .group_by(col(SopAcknowledgement.sop_id))
    ).all()
    return dict(rows)


def _card(actor: Actor, sop: Sop, acknowledged: dict[uuid.UUID, int]) -> SopCard:
    return SopCard(
        id=sop.id,
        title=sop.title,
        applies_to_roles=list(sop.applies_to_roles),
        required_for_onboarding=sop.required_for_onboarding,
        current_version=sop.current_version,
        updated_at=sop.updated_at,
        applies_to_me=applies(sop, actor.role_codes),
        my_acknowledged_version=acknowledged.get(sop.id),
    )


def list_sops(*, actor: Actor) -> list[SopCard]:
    with _transaction(actor) as session:
        sops = session.exec(
            select(Sop)
            .where(Sop.tenant_id == actor.tenant_id)
            .order_by(func.lower(col(Sop.title)), col(Sop.id))
        ).all()
        acknowledged = _acknowledged(
            session, tenant_id=actor.tenant_id, user_id=actor.user_id
        )
        return [_card(actor, sop, acknowledged) for sop in sops if _visible(actor, sop)]


def _detail(session: Session, actor: Actor, sop: Sop) -> SopDetail:
    versions = session.exec(
        select(SopVersion)
        .where(SopVersion.tenant_id == actor.tenant_id, SopVersion.sop_id == sop.id)
        .order_by(col(SopVersion.version).desc())
    ).all()
    names = users_roles.display_names(
        session,
        tenant_id=actor.tenant_id,
        user_ids=[version.published_by for version in versions],
    )
    current = next(v for v in versions if v.version == sop.current_version)
    card = _card(
        actor,
        sop,
        _acknowledged(session, tenant_id=actor.tenant_id, user_id=actor.user_id),
    )
    return SopDetail(
        **card.model_dump(),
        body=current.body,
        versions=[
            SopVersionRead(
                version=v.version,
                published_at=v.published_at,
                published_by_name=names.get(v.published_by),
            )
            for v in versions
        ],
    )


def _load(
    session: Session, actor: Actor, sop_id: uuid.UUID, *, lock: bool = False
) -> Sop:
    query = select(Sop).where(Sop.tenant_id == actor.tenant_id, Sop.id == sop_id)
    if lock:
        query = query.with_for_update()
    sop = session.exec(query).first()
    if sop is None or not _visible(actor, sop):
        raise _not_found()
    return sop


def read_sop(*, actor: Actor, sop_id: uuid.UUID) -> SopDetail:
    with _transaction(actor) as session:
        return _detail(session, actor, _load(session, actor, sop_id))


def _publish(session: Session, actor: Actor, sop: Sop, body: SopWrite) -> None:
    session.add(
        SopVersion(
            tenant_id=actor.tenant_id,
            sop_id=sop.id,
            version=sop.current_version,
            title=body.title,
            body=body.body,
            published_by=actor.user_id,
        )
    )
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=PUBLISH,
            result="SUCCESS",
            resource_id=sop.id,
            payload={"version": sop.current_version},
        ),
    )


def create_sop(*, actor: Actor, body: SopWrite) -> SopDetail:
    """A new SOP and its version 1 (R5, R6)."""
    with _transaction(actor) as session:
        sop = Sop(
            tenant_id=actor.tenant_id,
            title=body.title,
            applies_to_roles=body.applies_to_roles,
            required_for_onboarding=body.required_for_onboarding,
            current_version=1,
            created_by=actor.user_id,
        )
        session.add(sop)
        session.flush()
        _publish(session, actor, sop, body)
        return _detail(session, actor, sop)


def publish_version(*, actor: Actor, sop_id: uuid.UUID, body: SopWrite) -> SopDetail:
    """The next version (R6). Everyone it applies to must acknowledge it again (R7)."""
    with _transaction(actor) as session:
        sop = _load(session, actor, sop_id, lock=True)
        sop.title = body.title
        sop.applies_to_roles = body.applies_to_roles
        sop.required_for_onboarding = body.required_for_onboarding
        sop.current_version += 1
        sop.updated_at = datetime.now(UTC)
        session.add(sop)
        session.flush()
        _publish(session, actor, sop, body)
        return _detail(session, actor, sop)


def acknowledge(*, actor: Actor, sop_id: uuid.UUID, version: int) -> SopCard:
    """Acknowledge the current version. Idempotent; an older version is `409`; an SOP that does not
    apply to the caller is `404` (R7)."""
    with _transaction(actor) as session:
        sop = session.exec(
            select(Sop).where(Sop.tenant_id == actor.tenant_id, Sop.id == sop_id)
        ).first()
        if sop is None or not applies(sop, actor.role_codes):
            raise _not_found()
        if version != sop.current_version:
            raise SopRefused(
                status.HTTP_409_CONFLICT,
                NOT_CURRENT_VERSION,
                f"Version {sop.current_version} is current; acknowledge that one.",
            )
        inserted = session.exec(
            insert(SopAcknowledgement)
            .values(
                tenant_id=actor.tenant_id,
                sop_id=sop.id,
                version=version,
                user_id=actor.user_id,
                acknowledged_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(
                constraint="uq_sop_acknowledgements_tenant_sop_version_user"
            )
            .returning(col(SopAcknowledgement.id))
        ).first()
        if inserted is not None:
            audit.record(
                session,
                audit.AuditEvent(
                    action=ACKNOWLEDGE,
                    result="SUCCESS",
                    resource_id=sop.id,
                    payload={"version": version},
                ),
            )
        return _card(actor, sop, {sop.id: version})


def matrix(*, actor: Actor) -> AcknowledgementMatrix:
    """Active staff x SOP x the newest version each acknowledged (R8)."""
    staff = users_roles.list_staff(tenant_id=actor.tenant_id, skip=0, limit=1000).data
    with _transaction(actor) as session:
        sops = session.exec(
            select(Sop)
            .where(Sop.tenant_id == actor.tenant_id)
            .order_by(func.lower(col(Sop.title)), col(Sop.id))
        ).all()
        rows = session.exec(
            select(
                SopAcknowledgement.user_id,
                SopAcknowledgement.sop_id,
                func.max(SopAcknowledgement.version),
            )
            .where(SopAcknowledgement.tenant_id == actor.tenant_id)
            .group_by(col(SopAcknowledgement.user_id), col(SopAcknowledgement.sop_id))
        ).all()
        acknowledged: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
        for user_id, sop_id, version in rows:
            acknowledged.setdefault(user_id, {})[sop_id] = version
        return AcknowledgementMatrix(
            sops=[
                MatrixSop(
                    id=sop.id,
                    title=sop.title,
                    current_version=sop.current_version,
                    applies_to_roles=list(sop.applies_to_roles),
                )
                for sop in sops
            ],
            staff=[
                MatrixRow(
                    user_id=member.id,
                    name=member.full_name or member.email,
                    role_codes=sorted({role.code for role in member.roles}),
                    acknowledged=acknowledged.get(member.id, {}),
                    applicable=[
                        sop.id
                        for sop in sops
                        if applies(sop, {role.code for role in member.roles})
                    ],
                )
                for member in staff
                if member.status != "INACTIVE"
            ],
        )
