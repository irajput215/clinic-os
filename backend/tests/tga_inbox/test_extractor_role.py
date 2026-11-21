"""The extractor role (FEAT-09 R14, migration `9c4e2b7d1a05`): ingestion cannot write clinical state.

R14: *"Extractor role cannot write `tga_approvals`; the verify endpoint is the only writer of `ACTIVE`;
grant inspection passes."* These tests ask PostgreSQL, not the code: the grants, a write attempted
under the role, and that the pipeline really runs under it.
"""

import uuid

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import event, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine
from app.modules.tga_inbox.pipeline import EXTRACTOR_ROLE
from tests.tga_inbox.conftest import Clinic, InboxApi

_PRIVILEGE = text("SELECT has_table_privilege(:role, :table, :privilege)")


def _has(table: str, privilege: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                _PRIVILEGE,
                {"role": EXTRACTOR_ROLE, "table": table, "privilege": privilege},
            ).scalar_one()
        )


def test_the_role_cannot_log_in_or_bypass_row_level_security() -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolcanlogin, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = :r"
            ),
            {"r": EXTRACTOR_ROLE},
        ).one()
        member = conn.execute(
            text("SELECT pg_has_role('clinos_app', :r, 'MEMBER')"),
            {"r": EXTRACTOR_ROLE},
        ).scalar_one()
    assert tuple(row) == (False, False, False)
    assert member is True


def test_grant_inspection_matches_the_design() -> None:
    for table in (
        "tga_inbox_messages",
        "tga_inbox_attachments",
        "tga_extraction_results",
        "audit_log",
    ):
        assert _has(table, "SELECT") and _has(table, "INSERT"), table
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not _has(table, privilege), (table, privilege)
    for table in (
        "tga_approvals",
        "tga_approval_events",
        "patients",
        "prescriptions",
        "clinical_records",
    ):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not _has(table, privilege), (table, privilege)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO tga_approvals (id) VALUES (gen_random_uuid())",
        "UPDATE tga_approvals SET state = 'ACTIVE'",
        "SELECT 1 FROM patients LIMIT 1",
        "UPDATE tga_extraction_results SET accepted_value = NULL",
        "UPDATE tga_inbox_messages SET processing_state = 'VERIFIED'",
    ],
)
def test_the_database_refuses_anything_outside_ingestion(statement: str) -> None:
    with engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL ROLE {EXTRACTOR_ROLE}"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(uuid.uuid4())},
        )
        with pytest.raises(ProgrammingError) as refused:
            conn.execute(text(statement))
        assert isinstance(refused.value.orig, InsufficientPrivilege)


def test_ingestion_writes_under_the_role_and_the_connection_leaves_it(
    inbox: InboxApi, clinic: Clinic
) -> None:
    seen: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:  # type: ignore[no-untyped-def]
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        inbox.delivered(clinic.tenant_id)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    role_at = [i for i, s in enumerate(seen) if s == f"SET LOCAL ROLE {EXTRACTOR_ROLE}"]
    writes = [
        i
        for i, s in enumerate(seen)
        if s.startswith(("INSERT INTO tga_", "INSERT INTO audit_log"))
    ]
    assert role_at and writes
    # Every inbox or audit write the request made came after the switch into the role.
    assert min(writes) > min(role_at)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar_one() != EXTRACTOR_ROLE
