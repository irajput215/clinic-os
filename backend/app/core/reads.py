"""Independent reads in one round trip, decoded exactly as SQLAlchemy would decode them.

Every round trip to the database costs the full app-to-database latency
(`docs/reference/performance.md`), and a screen that already knows several things it will ask for
should not pay that latency once per question. This module queues SQLAlchemy `select`s and sends them
together on the caller's transaction (`app.core.db.run_pipelined`). The database still runs them one
after the other, each with its own snapshot, under the transaction's tenant context and RLS: only the
waiting is shared.

Three pieces:

- `ReadBatch` queues reads and sends them in one flight. Each queued read hands back a `Pending`
  whose `value` exists once the batch was sent. Rows are decoded with the statement's own column
  types (the result processing SQLAlchemy itself applies) and shaped the way `session.exec` shapes
  them: tuples for several columns, values for one, and `Model` instances for `select(Model)`,
  detached, exactly like rows loaded by a session that has since closed.
- A `Plan` is a generator that yields one `ReadBatch` per step and returns its result. It reads like
  sequential code: queue the reads, `yield` the batch, use the values, queue the next step.
- `Lockstep` advances several plans together, so the n-th step of every plan shares one flight. This
  is how a page made of several modules' sections (the Today page) reads each module's tables through
  that module's own facade and still pays one round trip per step rather than one per query.

A plan may run ordinary statements on the session between its steps (an audit write, say): they run
in order on the same transaction. A batch flushes the session before it is sent, so a read sees the
session's pending changes exactly as an autoflushing query would.
"""

from collections.abc import Callable, Generator, Sequence
from typing import Any, Final, cast

from sqlalchemy import inspect
from sqlalchemy.orm import Mapper, make_transient_to_detached
from sqlmodel import Session
from sqlmodel.sql.expression import Select, SelectOfScalar

from app.core.db import driver_statement, engine, run_pipelined_described

_UNSET: Final = object()

type _Rows = list[tuple[Any, ...]]
type _Decoder = Callable[[list[int], _Rows], Any]
type _Result = tuple[list[int], _Rows]


class Unsent(RuntimeError):
    """A pending read was used before its batch was sent: a programming error, never data."""


class Pending[T]:
    """The value of a queued read, available once the batch that holds it has been sent."""

    __slots__ = ("_compute", "_value")

    def __init__(self, compute: Callable[[], T]) -> None:
        self._compute = compute
        self._value: object = _UNSET

    @classmethod
    def ready(cls, value: T) -> Pending[T]:
        """A value known without asking the database (an empty `IN` list, say)."""
        return cls(lambda: value)

    @property
    def value(self) -> T:
        if self._value is _UNSET:
            self._value = self._compute()
        return cast(T, self._value)

    def then[R](self, transform: Callable[[T], R]) -> Pending[R]:
        """A value derived from this one, computed when first read."""
        return Pending(lambda: transform(self.value))


def _row_decoder(
    statement: Select[Any] | SelectOfScalar[Any],
) -> Callable[[list[int], _Rows], _Rows]:
    """Decode raw driver rows with each selected column's own type, as SQLAlchemy's result does."""
    dialect = engine.dialect
    types = [column.type.dialect_impl(dialect) for column in statement.selected_columns]

    def decode(type_codes: list[int], rows: _Rows) -> _Rows:
        processors = [
            type_.result_processor(dialect, type_code)
            for type_, type_code in zip(types, type_codes, strict=True)
        ]
        return [
            tuple(
                value if processor is None else processor(value)
                for processor, value in zip(processors, row, strict=True)
            )
            for row in rows
        ]

    return decode


class ReadBatch:
    """Reads queued for one flight on the caller's transaction (see the module docstring)."""

    def __init__(self) -> None:
        self._statements: list[tuple[str, dict[str, Any]]] = []
        self._decoders: list[_Decoder] = []
        self._results: list[Any] | None = None

    def _queue(
        self, statement: Select[Any] | SelectOfScalar[Any], decode: _Decoder
    ) -> Callable[[], Any]:
        index = len(self._statements)
        self._statements.append(driver_statement(statement))
        self._decoders.append(decode)

        def result() -> Any:  # noqa: ANN401 - typed by the public methods below
            if self._results is None:
                raise Unsent("read before its batch was sent")
            return self._results[index]

        return result

    def rows[TP: tuple[Any, ...]](self, statement: Select[TP]) -> Pending[list[TP]]:
        """Queue a select of several columns; its rows come back as tuples, decoded by type."""
        return Pending(self._queue(statement, _row_decoder(statement)))

    def scalars[T](self, statement: SelectOfScalar[T]) -> Pending[list[T]]:
        """Queue a select of one column or one mapped class, read as `session.exec` reads it.

        A column comes back as its decoded values; `select(Model)` comes back as detached `Model`
        instances, the way a session that has since closed leaves the rows it loaded.
        """
        decode_rows = _row_decoder(statement)
        [description] = statement.column_descriptions
        mapper = inspect(description["expr"], raiseerr=False)
        if not isinstance(mapper, Mapper):

            def decode_values(type_codes: list[int], rows: _Rows) -> list[Any]:
                return [value for (value,) in decode_rows(type_codes, rows)]

            return Pending(self._queue(statement, decode_values))

        keys = [
            mapper.get_property_by_column(column).key
            for column in statement.selected_columns
        ]

        def decode_instances(type_codes: list[int], rows: _Rows) -> list[Any]:
            instances = []
            for row in decode_rows(type_codes, rows):
                instance = mapper.class_(**dict(zip(keys, row, strict=True)))
                make_transient_to_detached(instance)
                instances.append(instance)
            return instances

        return Pending(self._queue(statement, decode_instances))

    def send(self, session: Session) -> None:
        """Send every queued read in one flight. An empty batch costs nothing."""
        _send_together(session, [self])


def _send_together(session: Session, batches: Sequence[ReadBatch]) -> None:
    """Send several batches as one flight; each keeps its own results."""
    if any(batch._results is not None for batch in batches):
        raise RuntimeError("a batch is sent once")
    statements = [statement for batch in batches for statement in batch._statements]
    results: list[_Result] = []
    if statements:
        session.flush()
        results = run_pipelined_described(session, statements)
    position = 0
    for batch in batches:
        batch._results = [
            decode(*results[position + offset])
            for offset, decode in enumerate(batch._decoders)
        ]
        position += len(batch._decoders)


#: A read plan: yields one batch per step and returns its result (see the module docstring).
type Plan[T] = Generator[ReadBatch, None, T]


class Lockstep:
    """Plans advanced together: the n-th step of every plan shares one flight."""

    def __init__(self) -> None:
        self._plans: list[Plan[Any]] = []
        self._results: dict[int, Any] = {}

    def add[T](self, plan: Plan[T]) -> Pending[T]:
        """Add a plan; its result is the returned value's `value` once `run` has finished."""
        index = len(self._plans)
        self._plans.append(plan)

        def result() -> T:
            if index not in self._results:
                raise Unsent("read before the plans were run")
            return cast(T, self._results[index])

        return Pending(result)

    def run(self, session: Session) -> None:
        """Run every plan to its end, one flight per step."""
        active: list[tuple[int, ReadBatch]] = []

        def advance(index: int, first: bool) -> None:
            plan = self._plans[index]
            try:
                batch = next(plan) if first else plan.send(None)
            except StopIteration as finished:
                self._results[index] = finished.value
            else:
                active.append((index, batch))

        for index in range(len(self._plans)):
            advance(index, first=True)
        while active:
            step, active = active, []
            _send_together(session, [batch for _, batch in step])
            for index, _ in step:
                advance(index, first=False)


def run_plan[T](session: Session, plan: Plan[T]) -> T:
    """Run one plan on its own: one flight per step."""
    lockstep = Lockstep()
    result = lockstep.add(plan)
    lockstep.run(session)
    return result.value
