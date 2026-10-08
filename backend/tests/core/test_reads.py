"""Batched reads (`app/core/reads.py`): one flight, the same rows a session would load, tenant-scoped.

Each property guards a way the batching could go wrong silently:

1. **Decoding**: a batched read returns exactly what the same statement returns through a session,
   type for type (a numeric, a range, an expanded `IN` list, a mapped entity).
2. **Isolation**: batched reads run on the caller's transaction, under its tenant context, so RLS
   bounds them like any other read (asserted as `clinos_app`, which the policy binds).
3. **Cost**: a batch, and the n-th step of every plan in a `Lockstep`, is one round trip.
4. **Misuse fails loudly**: reading a value before its batch was sent raises, never returns nothing.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Numeric, cast, func, literal, text
from sqlalchemy.dialects.postgresql import DATERANGE
from sqlmodel import col, select

from app.core.db import engine, tenant_transaction
from app.core.reads import Lockstep, Pending, Plan, ReadBatch, Unsent, run_plan
from app.core.server_timing import end_request, start_request
from app.modules.clinics.models import Clinic
from tests.utils.seeding import create_clinic, create_tenant, delete_tenancy_rows

AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")


@pytest.fixture
def two_tenants() -> Iterator[dict[str, uuid.UUID]]:
    with engine.begin() as conn:
        a = create_tenant(conn, name="Reads A")
        b = create_tenant(conn, name="Reads B")
        create_clinic(conn, tenant_id=a, name="Alpha Reads Site")
        create_clinic(conn, tenant_id=a, name="Alpha Reads Annex")
        create_clinic(conn, tenant_id=b, name="Beta Reads Site")
    yield {"a": a, "b": b}
    with engine.begin() as conn:
        delete_tenancy_rows(conn, a, b)


def test_rows_are_decoded_as_a_session_decodes_them() -> None:
    statement = select(
        cast(literal("1.50"), Numeric(10, 2)),
        cast(literal("[2026-01-01,2026-02-01)"), DATERANGE),
        literal(date(2026, 1, 2)),
    )
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        batch = ReadBatch()
        batched = batch.rows(statement)
        batch.send(session)
        loaded = session.exec(statement).one()

    [row] = batched.value
    assert row == tuple(loaded)
    assert row[0] == Decimal("1.50")
    assert row[1].lower == date(2026, 1, 1)


def test_entities_are_the_rows_a_session_loads(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    tenant_id = two_tenants["a"]
    with tenant_transaction(tenant_id=tenant_id) as session:
        ids = list(
            session.exec(select(Clinic.id).where(Clinic.tenant_id == tenant_id)).all()
        )
        statement = (
            select(Clinic).where(col(Clinic.id).in_(ids)).order_by(col(Clinic.name))
        )
        batch = ReadBatch()
        batched = batch.entities(statement)
        batch.send(session)
        loaded = [clinic.model_dump() for clinic in session.exec(statement).all()]

    assert [clinic.model_dump() for clinic in batched.value] == loaded
    assert [clinic.name for clinic in batched.value] == [
        "Alpha Reads Annex",
        "Alpha Reads Site",
    ]
    assert all(isinstance(clinic, Clinic) for clinic in batched.value)


def test_batched_reads_run_under_the_transactions_tenant_context(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """No tenant predicate in the statement: only RLS, under this transaction's context, bounds it."""
    with tenant_transaction(tenant_id=two_tenants["b"]) as session:
        session.connection().execute(AS_APP_ROLE)
        batch = ReadBatch()
        names = batch.rows(select(Clinic.name).order_by(col(Clinic.name)))
        setting = batch.rows(select(func.current_setting("app.tenant_id", True)))
        batch.send(session)

    assert names.value == [("Beta Reads Site",)]
    assert setting.value == [(str(two_tenants["b"]),)]


def test_a_batch_is_one_round_trip_and_an_empty_one_is_none() -> None:
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        session.connection().execute(text("SELECT 1"))
        timings, token = start_request()
        try:
            batch = ReadBatch()
            for value in range(5):
                batch.rows(select(literal(value)))
            batch.send(session)
            ReadBatch().send(session)
        finally:
            end_request(token)

    assert timings.db_round_trips == 1


def _two_step_plan(label: str, log: list[str]) -> Plan[tuple[str, int]]:
    first = ReadBatch()
    word = first.rows(select(literal(label)))
    yield first
    log.append(f"{label}: first step read")
    second = ReadBatch()
    length = second.rows(select(func.length(literal(word.value[0][0]))))
    yield second
    return word.value[0][0], length.value[0][0]


def _no_step_plan() -> Plan[str]:
    return "answered without the database"
    yield ReadBatch()  # pragma: no cover - makes this a generator


def test_lockstep_shares_one_flight_per_step_across_plans() -> None:
    log: list[str] = []
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        session.connection().execute(text("SELECT 1"))
        lockstep = Lockstep()
        short = lockstep.add(_two_step_plan("ab", log))
        long = lockstep.add(_two_step_plan("abcd", log))
        none = lockstep.add(_no_step_plan())
        timings, token = start_request()
        try:
            lockstep.run(session)
        finally:
            end_request(token)

    assert (short.value, long.value, none.value) == (
        ("ab", 2),
        ("abcd", 4),
        "answered without the database",
    )
    assert log == ["ab: first step read", "abcd: first step read"]
    assert timings.db_round_trips == 2


def test_run_plan_runs_one_plan_to_its_end() -> None:
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        assert run_plan(session, _two_step_plan("abc", [])) == ("abc", 3)


def test_a_value_read_before_its_batch_was_sent_raises() -> None:
    batch = ReadBatch()
    pending = batch.rows(select(literal(1)))
    with pytest.raises(Unsent):
        _ = pending.value
    lockstep = Lockstep()
    result = lockstep.add(_no_step_plan())
    with pytest.raises(Unsent):
        _ = result.value


def test_a_batch_is_sent_once() -> None:
    with tenant_transaction(tenant_id=uuid.uuid4()) as session:
        batch = ReadBatch()
        batch.rows(select(literal(1)))
        batch.send(session)
        with pytest.raises(RuntimeError):
            batch.send(session)


def test_pending_values_compose() -> None:
    doubled = Pending.ready(21).then(lambda value: value * 2)
    assert doubled.value == 42
