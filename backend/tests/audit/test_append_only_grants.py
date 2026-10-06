"""S12a–S12g and R1/R2/R14/R15 — enforcement is by grant, not by convention.

`docs/features/04-audit-log/04-threat-model.md` T-AUD-1 and T-AUD-2, and Gate 2's checklist:
*"An `UPDATE` or `DELETE` against `audit_log` through the application role is refused"*, *"the
application role does not own the tables and has no `BYPASSRLS`"*.

Every assertion here reads the database catalogue or executes the refused statement as the role
itself. None of them reads the migration source: the migration says what was intended, and the
catalogue says what is true — the whole point of a grant over a convention is that the two can
disagree.

`SET ROLE clinos_app` is how the refusal is provoked. `clinos_app` is created `NOLOGIN PASSWORD NULL`
(a credential does not belong in a migration), so a test cannot connect as it; `SET ROLE` assumes the
role within an existing session, which is exactly what PostgreSQL checks privileges and policies
against. The `RESET ROLE` on the way out keeps the assumption from leaking to the next case.
"""

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine, tenant_transaction
from app.modules.audit import service
from tests.audit.conftest import audit_rows

REPO_BACKEND = Path(__file__).resolve().parents[2]

_GRANTS_ON_AUDIT_LOG = text(
    "SELECT privilege_type FROM information_schema.role_table_grants "
    "WHERE grantee = :grantee AND table_name = 'audit_log'"
)
_POLICIES = text(
    "SELECT policyname, cmd FROM pg_policies "
    "WHERE schemaname = 'public' AND tablename = 'audit_log' ORDER BY policyname"
)
_RLS_STATE = text(
    "SELECT relrowsecurity, relforcerowsecurity "
    "FROM pg_class WHERE relname = 'audit_log'"
)
_OWNER = text(
    "SELECT r.rolname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
    "WHERE c.relname = 'audit_log'"
)
_ROLE_ATTRIBUTES = text(
    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'clinos_app'"
)

# The exact refusal PostgreSQL raises for a missing table privilege. Asserting the SQLSTATE, not just
# "it raised", is what separates "the engine refused this" from "the statement was malformed".
INSUFFICIENT_PRIVILEGE = "42501"


def _sqlstate_of_a_refused_statement(statement: str) -> str | None:
    """Run one statement as `clinos_app` and return the SQLSTATE the engine refused it with.

    `None` means the statement was **allowed**, which is the failure this whole file exists to catch
    — the caller asserts on it. Each statement gets its own connection inside its own transaction:
    a failed statement aborts that transaction in PostgreSQL, so a shared connection would poison
    every case after the first refusal.
    """
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL ROLE clinos_app"))
            try:
                conn.execute(text(statement))
            except ProgrammingError as error:
                if error.orig is None:
                    return None
                return str(getattr(error.orig, "sqlstate", ""))
    return None


def _assert_refused(statement: str) -> None:
    refused_with = _sqlstate_of_a_refused_statement(statement)
    assert refused_with == INSUFFICIENT_PRIVILEGE, (
        f"`clinos_app` ran {statement!r} (SQLSTATE {refused_with!r}). Expected "
        f"{INSUFFICIENT_PRIVILEGE} insufficient_privilege: the append-only control is a convention "
        "again"
    )


def test_app_role_has_exactly_select_insert() -> None:
    """S12a / R1: the privilege set read after every migration is exactly `{SELECT, INSERT}`."""
    with engine.connect() as conn:
        granted = {
            row[0]
            for row in conn.execute(_GRANTS_ON_AUDIT_LOG, {"grantee": "clinos_app"})
        }
    assert granted == {"SELECT", "INSERT"}, (
        "`clinos_app` holds "
        f"{sorted(granted)} on `audit_log`. R1 requires exactly "
        "{'INSERT', 'SELECT'} — a `TRUNCATE`, `UPDATE` or `DELETE` here means the append-only "
        "control is a convention again"
    )


def test_the_readonly_audit_role_holds_select_and_nothing_else() -> None:
    """The design's auditor role: `SELECT` only. A role that can `INSERT` can forge an event."""
    with engine.connect() as conn:
        granted = {
            row[0]
            for row in conn.execute(
                _GRANTS_ON_AUDIT_LOG, {"grantee": "clinos_readonly_audit"}
            )
        }
    assert granted == {"SELECT"}, (
        f"`clinos_readonly_audit` holds {sorted(granted)}; the design gives it `SELECT` only"
    )


def test_app_role_cannot_update_audit_log() -> None:
    """S12b / R2: the signature attack from T-AUD-1, refused by the engine."""
    _assert_refused(
        "UPDATE audit_log SET reason = 'tampered' WHERE tenant_id = gen_random_uuid()"
    )


def test_app_role_cannot_delete_audit_log() -> None:
    """S12c / R2."""
    _assert_refused("DELETE FROM audit_log WHERE tenant_id = gen_random_uuid()")


def test_app_role_cannot_truncate_audit_log() -> None:
    """S12d / R2: a table wipe is a `TRUNCATE`, and it is refused like the other two."""
    _assert_refused("TRUNCATE audit_log")


def test_app_role_is_not_owner_and_has_no_bypassrls() -> None:
    """S12e / R15. `FORCE` removes the owner's exemption; it does not make ownership safe."""
    with engine.connect() as conn:
        owner = conn.execute(_OWNER).scalar_one()
        assert str(owner) != "clinos_app", (
            "`clinos_app` owns `audit_log` — an owner can drop the policy that constrains it"
        )
        rolsuper, rolbypassrls = conn.execute(_ROLE_ATTRIBUTES).one()
        assert rolsuper is False, "`clinos_app` is SUPERUSER"
        assert rolbypassrls is False, (
            "`clinos_app` holds BYPASSRLS, which makes every policy in this schema decorative"
        )


def test_no_update_or_delete_policy_and_force_rls() -> None:
    """S12f / R14. Two policies only: an `INSERT` `WITH CHECK` and a `SELECT` `USING`."""
    with engine.connect() as conn:
        policies = {row[0]: row[1] for row in conn.execute(_POLICIES)}
        rls, forced = conn.execute(_RLS_STATE).one()

    assert set(policies) == {"audit_log_insert", "audit_log_select"}, (
        f"`audit_log` carries {sorted(policies)}; the design allows exactly the insert policy and "
        "the select policy, because a `FOR ALL` policy would create the UPDATE and DELETE policies "
        "it forbids"
    )
    assert policies["audit_log_insert"] == "INSERT", (
        "`audit_log_insert` is not an INSERT policy"
    )
    assert policies["audit_log_select"] == "SELECT", (
        "`audit_log_select` is not a SELECT policy"
    )
    assert rls is True, "ROW LEVEL SECURITY is not ENABLED on `audit_log`"
    assert forced is True, (
        "ROW LEVEL SECURITY is not FORCED, so the table owner bypasses every policy"
    )


def test_no_update_or_delete_statement_in_source() -> None:
    """S12g: a repository lint rule over the **application**, so the statement cannot be written by
    accident either.

    The grant makes an `UPDATE audit_log` *fail*; this makes it *reviewable*. Both are wanted: the
    first is prevention, the second is the reason nobody spends an afternoon wondering why the first
    one fired.

    The rule covers `backend/app` and `backend/scripts` — the code that runs against the production
    database. `backend/tests` is excluded on purpose and not to make the rule pass: this very file and
    `test_write_path.py` contain the tamper statements the verification tests need, and the
    distinguished case is that they run as the **owner**, which is the attacker the chain exists to
    detect. A rule that forbade its own negative tests would be a rule that cannot be tested.
    """
    pattern = re.compile(
        r"\b(UPDATE\s+audit_log|DELETE\s+FROM\s+audit_log)\b", re.IGNORECASE
    )
    offenders: list[str] = []
    for root in (REPO_BACKEND / "app", REPO_BACKEND / "scripts"):
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            for match in pattern.finditer(source):
                line = source[: match.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(REPO_BACKEND)}:{line}: {match.group(0)}"
                )

    assert not offenders, (
        "these files contain a statement against the append-only table — `clinos_app` cannot run it, "
        "and no production code should be shaped as if it could:\n  "
        + "\n  ".join(offenders)
    )


def test_a_rolled_back_caller_leaves_no_audit_row() -> None:
    """F2 at the transaction boundary: the writer has no commit of its own.

    S12h is the end-to-end version (an endpoint whose audit write fails); this is the same property
    one level down, so a failure here names the writer rather than the route. It needs no
    organisation: a tenant identifier and the writer are the whole fixture, which keeps this file
    cheap enough to run on its own.
    """
    tenant_id = uuid.uuid4()
    with pytest.raises(RuntimeError, match="rollback on purpose"):
        with tenant_transaction(tenant_id=tenant_id) as session:
            service.record(
                session,
                service.AuditEvent(
                    action="patient.read",
                    result="SUCCESS",
                    payload={"purpose": "TREATMENT"},
                ),
            )
            raise RuntimeError("rollback on purpose")

    assert audit_rows(tenant_id) == [], (
        "the rolled-back transaction left an audit row behind; the writer is committing on its own"
    )
