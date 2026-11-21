"""The Parchment adapter (D-012): resilience, minimum-data payload, outcome mapping, and the real
outbox drain sending through it to the simulated Parchment. Nothing leaves the process."""

import uuid
from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal

from app.core.config import settings
from app.modules.prescriptions import outbox
from app.modules.prescriptions.transport import (
    Confirmed,
    DispatchRequest,
    ExplicitUnknown,
    NotSent,
    Rejected,
    TransportOutcome,
    configured_transport,
)
from app.modules.prescriptions.transports.identities import load_dispatch_identities
from app.modules.prescriptions.transports.parchment import (
    PAYLOAD_FIELDS,
    DispatchIdentities,
    IdentityGap,
    ParchmentTransport,
    PatientIdentity,
    PrescriberIdentity,
    SimulatedParchmentWire,
    WireAnswer,
    build_payload,
)
from app.modules.prescriptions.transports.resilience import ResilientTransport
from tests.prescriptions.conftest import Clinic, RxApi
from tests.tga_inbox.conftest import luhn_complete
from tests.utils.onboarding import step_up

API = settings.API_V1_STR
IHI = luhn_complete("800360" + "555555555")
HPI_I = luhn_complete("800361" + "444444444")


def _request(**overrides: object) -> DispatchRequest:
    values: dict[str, object] = {
        "prescription_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "patient_id": uuid.uuid4(),
        "prescriber_id": uuid.uuid4(),
        "approval_id": uuid.uuid4(),
        "medicine_name": "Synthetic Oil 10:10",
        "tga_category": "CATEGORY_3",
        "dosage_form": "ORAL_LIQUID",
        "dose_instruction": "0.5 mL twice daily",
        "quantity": Decimal("25.000"),
        "repeats": 2,
        "date_of_service": date(2026, 6, 1),
    }
    values.update(overrides)
    return DispatchRequest(**values)  # type: ignore[arg-type]


IDENTITIES = DispatchIdentities(
    prescriber=PrescriberIdentity("Dr Grace Example", HPI_I, "1234567"),
    patient=PatientIdentity(
        given_name="Ada",
        family_name="Synthetic",
        date_of_birth=date(1990, 1, 1),
        sex="FEMALE",
        ihi=IHI,
        address_line="1 Example St",
        suburb="Testville",
        state="NSW",
        postcode="2000",
    ),
    tga_approval_reference="SAS-2026-000001",
)


def _adapter(wire: SimulatedParchmentWire, identities=IDENTITIES) -> ParchmentTransport:  # type: ignore[no-untyped-def]
    return ParchmentTransport(wire=wire, identities=lambda _request: identities)


# -- payload ----------------------------------------------------------------------------------------


def test_the_payload_allow_list_is_pinned_and_internal_ids_never_leave() -> None:
    assert PAYLOAD_FIELDS == (
        "clinicos_prescription_id",
        "prescriber_name", "prescriber_hpi_i", "prescriber_number",
        "patient_given_name", "patient_family_name", "patient_date_of_birth", "patient_sex",
        "patient_ihi", "patient_address_line", "patient_suburb", "patient_state",
        "patient_postcode", "patient_medicare_number", "patient_medicare_irn",
        "medicine_name", "dosage_form", "dose_instruction", "quantity", "repeats",
        "date_of_service", "tga_category", "tga_approval_reference",
    )  # fmt: skip
    request = _request()
    payload = build_payload(request, IDENTITIES)
    sent = {f.name: getattr(payload, f.name) for f in fields(payload)}
    for internal in (
        request.tenant_id,
        request.patient_id,
        request.prescriber_id,
        request.approval_id,
    ):
        assert str(internal) not in map(str, sent.values())
    assert sent["quantity"] == "25"
    assert sent["patient_ihi"] == IHI


def test_no_identity_or_payload_prints_its_values() -> None:
    payload = build_payload(_request(), IDENTITIES)
    for value in (payload, IDENTITIES.patient, IDENTITIES.prescriber):
        assert (
            IHI not in repr(value)
            and "Synthetic" not in repr(value)
            and HPI_I not in repr(value)
        )


# -- outcome mapping ----------------------------------------------------------------------------------


def test_every_provider_answer_maps_to_exactly_one_outbox_outcome() -> None:
    cases: list[tuple[WireAnswer, type]] = [
        (WireAnswer("ACCEPTED", provider_reference="P-1"), Confirmed),
        (
            WireAnswer("ACCEPTED"),
            ExplicitUnknown,
        ),  # a confirmation without a reference is not trusted
        (WireAnswer("REJECTED", error_class="INVALID_PRESCRIBER"), Rejected),
        (WireAnswer("UNKNOWN", error_class="READ_TIMEOUT"), ExplicitUnknown),
        (WireAnswer("NOT_SENT", error_class="CONNECTION_REFUSED"), NotSent),
        (WireAnswer("NOT_FOUND"), ExplicitUnknown),
    ]
    for answer, expected in cases:
        wire = SimulatedParchmentWire()
        wire.create = lambda *a, answer=answer, **k: answer  # type: ignore[method-assign]
        outcome = _adapter(wire).send(
            _request(), idempotency_key="k", deadline_seconds=20
        )
        assert isinstance(outcome, expected), (answer, outcome)


def test_lookup_maps_found_and_never_created() -> None:
    wire = SimulatedParchmentWire()
    adapter = _adapter(wire)
    assert isinstance(
        adapter.lookup(idempotency_key="nope", provider_reference=None), Rejected
    )
    adapter.send(_request(), idempotency_key="yes", deadline_seconds=20)
    assert isinstance(
        adapter.lookup(idempotency_key="yes", provider_reference=None), Confirmed
    )
    wire.status_answer = WireAnswer("UNKNOWN", error_class="READ_TIMEOUT")
    assert isinstance(
        adapter.lookup(idempotency_key="yes", provider_reference=None), ExplicitUnknown
    )


def test_a_missing_identity_is_refused_before_anything_is_built_or_sent() -> None:
    wire = SimulatedParchmentWire()
    adapter = _adapter(wire, identities=IdentityGap(("IHI", "HPI_I")))
    outcome = adapter.send(_request(), idempotency_key="k", deadline_seconds=20)
    assert outcome == Rejected("IDENTITY_INCOMPLETE_HPI_I_IHI")
    assert wire.payloads == []


def test_the_same_key_never_creates_two_prescriptions() -> None:
    wire = SimulatedParchmentWire()
    adapter = _adapter(wire)
    first = adapter.send(_request(), idempotency_key="same", deadline_seconds=20)
    second = adapter.send(_request(), idempotency_key="same", deadline_seconds=20)
    assert first == second and len(wire.created) == 1


# -- resilience ------------------------------------------------------------------------------------


@dataclass
class _Scripted:
    outcomes: list[TransportOutcome]
    calls: list[float] = field(default_factory=list)
    provider: str = "scripted"

    def send(
        self, request: DispatchRequest, *, idempotency_key: str, deadline_seconds: float
    ) -> TransportOutcome:
        self.calls.append(deadline_seconds)
        return self.outcomes.pop(0) if self.outcomes else Confirmed("LAST")

    def lookup(
        self, *, idempotency_key: str, provider_reference: str | None
    ) -> TransportOutcome:
        return self.outcomes.pop(0)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _resilient(inner: _Scripted, clock: _Clock, **kwargs: object) -> ResilientTransport:
    return ResilientTransport(
        inner=inner, sleep=clock.sleep, clock=clock, jitter=lambda: 1.0, **kwargs
    )  # type: ignore[arg-type]


def test_only_a_transient_not_sent_is_retried_at_most_four_times() -> None:
    clock = _Clock()
    inner = _Scripted([NotSent("CONNECTION_REFUSED")] * 3 + [Confirmed("P-9")])
    assert _resilient(inner, clock).send(
        _request(), idempotency_key="k", deadline_seconds=120
    ) == Confirmed("P-9")
    assert len(inner.calls) == 4 and clock.now == 1 + 4 + 16
    inner = _Scripted([NotSent("CONNECTION_REFUSED")] * 6)
    assert _resilient(inner, _Clock()).send(
        _request(), idempotency_key="k", deadline_seconds=500
    ) == NotSent("CONNECTION_REFUSED")
    assert len(inner.calls) == 4
    for outcome in (
        ExplicitUnknown("READ_TIMEOUT"),
        Rejected("INVALID"),
        NotSent("CIRCUIT_OPEN"),
    ):
        inner = _Scripted([outcome])
        assert (
            _resilient(inner, _Clock()).send(
                _request(), idempotency_key="k", deadline_seconds=60
            )
            == outcome
        )
        assert len(inner.calls) == 1


def test_retries_stop_at_the_deadline_and_each_attempt_gets_what_is_left() -> None:
    clock = _Clock()
    inner = _Scripted([NotSent("SERVICE_UNAVAILABLE")] * 4)
    _resilient(inner, clock).send(_request(), idempotency_key="k", deadline_seconds=10)
    # 10 s left, a 1 s pause, 9 s left, a 4 s pause, 5 s left; a 16 s pause would pass the deadline.
    assert inner.calls == [10, 9, 5]


def test_the_breaker_opens_after_repeated_failures_and_lets_one_trial_through_later() -> (
    None
):
    clock = _Clock()
    inner = _Scripted([ExplicitUnknown("READ_TIMEOUT")] * 3)
    transport = _resilient(inner, clock, failure_threshold=3, reset_seconds=30)
    for _ in range(3):
        transport.send(_request(), idempotency_key="k", deadline_seconds=20)
    assert transport.send(
        _request(), idempotency_key="k", deadline_seconds=20
    ) == NotSent("CIRCUIT_OPEN")
    assert len(inner.calls) == 3
    clock.now += 31
    assert transport.send(
        _request(), idempotency_key="k", deadline_seconds=20
    ) == Confirmed("LAST")
    assert transport.send(
        _request(), idempotency_key="k", deadline_seconds=20
    ) == Confirmed("LAST")


def test_the_bulkhead_refuses_rather_than_queues() -> None:
    transport = _resilient(_Scripted([]), _Clock(), max_concurrent=0)
    assert transport.send(
        _request(), idempotency_key="k", deadline_seconds=20
    ) == NotSent("BULKHEAD_FULL")


def test_still_no_transport_is_configured() -> None:
    assert configured_transport() is None


# -- end to end: the real outbox drain through the adapter --------------------------------------------


def _escript_ready(rx: RxApi, clinic: Clinic) -> None:
    owner = clinic.owner
    patched = rx.client.patch(
        f"{API}/patients/{clinic.patient_id}",
        json={"ihi": IHI, "sex_at_birth": "FEMALE", "address_line": "1 Example St",
              "suburb": "Testville", "state": "NSW", "postcode": "2000"},
        headers=owner.headers,
    )  # fmt: skip
    assert patched.status_code == 200, patched.text
    put = rx.client.put(
        f"{API}/users/{owner.user_id}/identifiers/HPI_I",
        json={"value": HPI_I, "status": "ACTIVE", "verification_method": "HI Service",
              "step_up_token": step_up(rx.client, owner.headers, owner.password, owner.user_id)},
        headers=owner.headers,
    )  # fmt: skip
    assert put.status_code == 200, put.text


def _queued(rx: RxApi, clinic: Clinic) -> str:
    rx.approve(clinic, reference="SAS-E2E-0001")
    staged = rx.stage(clinic)
    assert rx.sign_raw(clinic.owner, staged["id"]).status_code == 200
    assert rx.dispatch_raw(clinic.owner, staged["id"]).status_code == 202
    return str(staged["id"])


def test_a_signed_script_is_sent_through_the_adapter_with_real_identities(
    rx: RxApi, clinic: Clinic
) -> None:
    _escript_ready(rx, clinic)
    prescription_id = _queued(rx, clinic)
    wire = SimulatedParchmentWire()
    transport = ResilientTransport(
        ParchmentTransport(wire=wire, identities=load_dispatch_identities)
    )
    report = outbox.drain(clinic.owner.tenant_id, transport)
    assert report.sent == 1
    assert rx.row(prescription_id)["state"] == "DISPATCHED"
    [payload] = wire.payloads
    assert payload.patient_ihi == IHI
    assert payload.prescriber_hpi_i == HPI_I
    assert payload.tga_approval_reference == "SAS-E2E-0001"
    assert payload.clinicos_prescription_id == prescription_id
    [attempt] = rx.attempts(prescription_id)
    assert attempt["provider_reference"] == next(iter(wire.created.values()))


def test_a_script_for_a_patient_without_an_ihi_fails_without_sending(
    rx: RxApi, clinic: Clinic
) -> None:
    prescription_id = _queued(rx, clinic)
    wire = SimulatedParchmentWire()
    outbox.drain(
        clinic.owner.tenant_id,
        ParchmentTransport(wire=wire, identities=load_dispatch_identities),
    )
    assert wire.payloads == []
    assert rx.row(prescription_id)["state"] == "FAILED"
    assert rx.attempts(prescription_id)[0]["error_class"].startswith(
        "IDENTITY_INCOMPLETE_"
    )


def test_a_lost_answer_is_reconciled_to_dispatched(rx: RxApi, clinic: Clinic) -> None:
    _escript_ready(rx, clinic)
    prescription_id = _queued(rx, clinic)
    wire = SimulatedParchmentWire(
        script=[
            WireAnswer(
                "UNKNOWN", provider_reference="P-LOST", error_class="READ_TIMEOUT"
            )
        ]
    )
    transport = ParchmentTransport(wire=wire, identities=load_dispatch_identities)
    outbox.drain(clinic.owner.tenant_id, transport)
    assert rx.row(prescription_id)["state"] == "REQUIRES_RECONCILIATION"
    outbox.reconcile(clinic.owner.tenant_id, transport)
    assert rx.row(prescription_id)["state"] == "DISPATCHED"
    assert rx.attempts(prescription_id)[0]["provider_reference"] == "P-LOST"
