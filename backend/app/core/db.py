"""Engine, session and the tenant-scoped transaction helper.

Tenant context is set with `SET LOCAL` inside the transaction that runs the query
and nowhere else, so a pooled connection cannot carry one tenant's context into
another tenant's request
(`docs/features/01-tenancy-and-clinics/03-design.md`, "The connection-pool hazard").
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlmodel import Session, create_engine, select, text

from app import crud
from app.core.config import settings
from app.models import User, UserCreate


class TenantContextRequired(RuntimeError):
    """No tenant context: refuse to open rather than run an unscoped query."""


engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


def _set_context(session: Session, key: str, value: str) -> None:
    # set_config(..., is_local => true) is the parameterisable form of SET LOCAL:
    # the value is bound, never interpolated into SQL. Raw SQL that returns no model
    # rows goes through the connection: SQLModel's `exec` overloads do not accept a
    # TextClause, and its `execute` shim is deprecated.
    session.connection().execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": key, "value": value},
    )


@contextmanager
def tenant_transaction(
    *,
    tenant_id: UUID | None,
    actor_id: UUID | None = None,
    request_id: str | None = None,
    actor_role: str | None = None,
    source_ip: str | None = None,
    correlation_id: str | None = None,
) -> Iterator[Session]:
    """Open one transaction carrying tenant context.

    Fails closed: without a tenant no transaction opens, so there is no path to an
    unscoped query. The settings are transaction-scoped, so they revert at COMMIT
    or ROLLBACK and cannot leak across pooled requests.

    **The audit writer reads its actor context from here, not from a parameter**
    (`app.modules.audit.service`). `app.tenant_id` is set with `SET LOCAL`, and the actor,
    role, request, source address and correlation identifiers are recorded on the session,
    so a caller cannot describe an audit event as coming from somebody else, and cannot
    chain one into another tenant's trail (INV-1). `actor_role` is the role held at
    decision time, which is why the caller supplies it rather than the writer
    re-deriving it later.
    """
    if tenant_id is None:
        raise TenantContextRequired(
            "tenant context is required; refusing to open an unscoped transaction"
        )

    with Session(engine) as session, session.begin():
        _set_context(session, "app.tenant_id", str(tenant_id))
        session.info["tenant_id"] = str(tenant_id)
        if actor_id is not None:
            _set_context(session, "app.actor_id", str(actor_id))
            session.info["actor_id"] = str(actor_id)
        if request_id is not None:
            _set_context(session, "app.request_id", request_id)
            session.info["request_id"] = request_id
        if actor_role is not None:
            session.info["actor_role"] = actor_role
        if source_ip is not None:
            session.info["source_ip"] = source_ip
        if correlation_id is not None:
            session.info["correlation_id"] = correlation_id
        yield session


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)
