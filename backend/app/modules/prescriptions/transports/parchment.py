"""The Parchment eRx adapter (D-012), behind the outbox's `DispatchTransport` interface.

```
outbox drain -> ResilientTransport -> ParchmentTransport -> ParchmentWire -> Parchment
                (deadline, retry,     (identities, minimum-  (HTTP; only the
                 breaker, bulkhead)    data payload, outcome  simulated wire
                                       mapping)               exists today)
```

## What is real and what is waiting

Real, and tested: the identity check before anything is built, the minimum-data payload with its
explicit field allow-list, the mapping of every provider answer to the outbox's four outcomes, and the
resilience controls around it.

Waiting for Parchment (D-012 open items): the HTTP wire. Parchment's API documentation and sandbox
have not been seen, so no endpoint, field name, auth scheme or status code of theirs is written here.
`ParchmentWire` is the seam a real client fills in: two calls, each answering a `WireAnswer` in
Parchment-neutral terms. When the docs arrive, the client maps their schema to `ParchmentPayload` and
their responses to `WireAnswer`, and nothing else changes.

## The payload is a privacy decision, written as code

`ParchmentPayload` names every field that may leave ClinicOS, and `build_payload` fills exactly those
from the signed prescription and the two identities. It is a DRAFT allow-list (D-012 §3): the Privacy
Officer signs off the final list against the rail schema, and a field Parchment does not require is
removed. Nothing is ever serialised from a model wholesale, so a column added to `prescriptions` or
`patients` later cannot leak into a request by accident.

`ParchmentPayload` is HIGHLY_SENSITIVE: it is never logged, never put in an error, and its `repr`
says so instead of printing it.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal
from typing import Final, Literal, Protocol

from app.modules.prescriptions.transport import (
    Confirmed,
    DispatchRequest,
    ExplicitUnknown,
    NotSent,
    Rejected,
    TransportOutcome,
)

PROVIDER: Final[str] = "parchment"
# FEAT-13 defaults for Parchment: connect 3 s, read 15 s.
CONNECT_TIMEOUT_SECONDS: Final[float] = 3.0
READ_TIMEOUT_SECONDS: Final[float] = 15.0


# -- identities ------------------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class PrescriberIdentity:
    full_name: str
    hpi_i: str
    prescriber_number: str

    def __repr__(self) -> str:
        return "PrescriberIdentity(<HIGHLY_SENSITIVE>)"


@dataclass(frozen=True, repr=False)
class PatientIdentity:
    given_name: str
    family_name: str
    date_of_birth: date
    sex: str
    ihi: str
    address_line: str
    suburb: str
    state: str
    postcode: str
    medicare_number: str | None = None
    medicare_irn: int | None = None

    def __repr__(self) -> str:
        return "PatientIdentity(<HIGHLY_SENSITIVE>)"


@dataclass(frozen=True)
class DispatchIdentities:
    prescriber: PrescriberIdentity
    patient: PatientIdentity
    tga_approval_reference: str


@dataclass(frozen=True)
class IdentityGap:
    """What an eScript needs and the records do not hold. Codes only, never values."""

    missing: tuple[str, ...]


IdentitySource = Callable[[DispatchRequest], DispatchIdentities | IdentityGap]


# -- the payload -------------------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class ParchmentPayload:
    """Every field that may be sent to Parchment, and nothing else. DRAFT (see the module docstring)."""

    # Correlation: ClinicOS's own id, so a provider answer can be matched to the prescription.
    clinicos_prescription_id: str
    # Prescriber
    prescriber_name: str
    prescriber_hpi_i: str
    prescriber_number: str
    # Patient
    patient_given_name: str
    patient_family_name: str
    patient_date_of_birth: str
    patient_sex: str
    patient_ihi: str
    patient_address_line: str
    patient_suburb: str
    patient_state: str
    patient_postcode: str
    patient_medicare_number: str | None
    patient_medicare_irn: int | None
    # The medicine, as signed
    medicine_name: str
    dosage_form: str
    dose_instruction: str
    quantity: str
    repeats: int
    date_of_service: str
    # The authority it is prescribed under (TGA SAS-B / Authorised Prescriber)
    tga_category: str
    tga_approval_reference: str

    def __repr__(self) -> str:
        return "ParchmentPayload(<HIGHLY_SENSITIVE>)"


#: The allow-list, derived from the dataclass so there is one definition. A test pins it, so adding a
#: field is a reviewed change rather than a side effect.
PAYLOAD_FIELDS: Final[tuple[str, ...]] = tuple(f.name for f in fields(ParchmentPayload))


def build_payload(
    request: DispatchRequest, identities: DispatchIdentities
) -> ParchmentPayload:
    """The request built field by field. `tenant_id`, `patient_id`, `prescriber_id` and `approval_id`
    are ClinicOS-internal and are not sent."""
    prescriber, patient = identities.prescriber, identities.patient
    quantity = (
        request.quantity.normalize()
        if isinstance(request.quantity, Decimal)
        else request.quantity
    )
    return ParchmentPayload(
        clinicos_prescription_id=str(request.prescription_id),
        prescriber_name=prescriber.full_name,
        prescriber_hpi_i=prescriber.hpi_i,
        prescriber_number=prescriber.prescriber_number,
        patient_given_name=patient.given_name,
        patient_family_name=patient.family_name,
        patient_date_of_birth=patient.date_of_birth.isoformat(),
        patient_sex=patient.sex,
        patient_ihi=patient.ihi,
        patient_address_line=patient.address_line,
        patient_suburb=patient.suburb,
        patient_state=patient.state,
        patient_postcode=patient.postcode,
        patient_medicare_number=patient.medicare_number,
        patient_medicare_irn=patient.medicare_irn,
        medicine_name=request.medicine_name,
        dosage_form=request.dosage_form,
        dose_instruction=request.dose_instruction,
        quantity=format(quantity, "f"),
        repeats=request.repeats,
        date_of_service=request.date_of_service.isoformat(),
        tga_category=request.tga_category,
        tga_approval_reference=identities.tga_approval_reference,
    )


# -- the wire --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WireAnswer:
    """A provider answer in Parchment-neutral terms; the real client maps Parchment's onto this.

    * `ACCEPTED`: the electronic prescription exists; `provider_reference` names it.
    * `REJECTED`: a definitive refusal (a 4xx that is not a timeout); never retried.
    * `UNKNOWN`: no trustworthy answer (timeout after sending, 5xx after sending, unparsable body).
    * `NOT_SENT`: provably never reached the provider (connection refused, DNS failure).
    * `NOT_FOUND`: a status lookup found nothing under the key: it was never created.
    """

    kind: Literal["ACCEPTED", "REJECTED", "UNKNOWN", "NOT_SENT", "NOT_FOUND"]
    provider_reference: str | None = None
    # The eScript token's reference, when the provider returns one. Not stored yet: holding it needs
    # a schema change and a decision on who delivers it to the patient (D-012 §2).
    token_reference: str | None = None
    error_class: str = "UNSPECIFIED"


class ParchmentWire(Protocol):
    def create(
        self, payload: ParchmentPayload, *, idempotency_key: str, timeout_seconds: float
    ) -> WireAnswer: ...

    def status(
        self,
        *,
        idempotency_key: str,
        provider_reference: str | None,
        timeout_seconds: float,
    ) -> WireAnswer: ...


def _send_outcome(answer: WireAnswer) -> TransportOutcome:
    if answer.kind == "ACCEPTED" and answer.provider_reference:
        return Confirmed(answer.provider_reference)
    if answer.kind == "REJECTED":
        return Rejected(answer.error_class)
    if answer.kind == "NOT_SENT":
        return NotSent(answer.error_class)
    # UNKNOWN, an ACCEPTED without a reference (cannot be reconciled, so not trusted), or NOT_FOUND
    # from a create (meaningless): never success, never failure.
    return ExplicitUnknown(
        answer.error_class if answer.kind == "UNKNOWN" else "UNEXPECTED_ANSWER"
    )


def _lookup_outcome(answer: WireAnswer) -> TransportOutcome:
    if answer.kind == "ACCEPTED" and answer.provider_reference:
        return Confirmed(answer.provider_reference)
    if answer.kind in ("REJECTED", "NOT_FOUND"):
        # Never created under this key, so it is safe to call failed.
        return Rejected(
            answer.error_class if answer.kind == "REJECTED" else "NOT_FOUND_AT_PROVIDER"
        )
    return ExplicitUnknown(answer.error_class)


@dataclass
class ParchmentTransport:
    """The adapter. Thread-safe as long as `wire` and `identities` are."""

    wire: ParchmentWire
    identities: IdentitySource

    @property
    def provider(self) -> str:
        return PROVIDER

    def send(
        self, request: DispatchRequest, *, idempotency_key: str, deadline_seconds: float
    ) -> TransportOutcome:
        if not idempotency_key:
            raise ValueError("a send needs an idempotency key")
        resolved = self.identities(request)
        if isinstance(resolved, IdentityGap):
            # Refused before anything is built or sent; the codes name what is missing, never a value.
            return Rejected(
                "IDENTITY_INCOMPLETE_" + "_".join(sorted(resolved.missing))[:40]
            )
        payload = build_payload(request, resolved)
        return _send_outcome(
            self.wire.create(
                payload,
                idempotency_key=idempotency_key,
                timeout_seconds=min(
                    deadline_seconds, CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS
                ),
            )
        )

    def lookup(
        self, *, idempotency_key: str, provider_reference: str | None
    ) -> TransportOutcome:
        return _lookup_outcome(
            self.wire.status(
                idempotency_key=idempotency_key,
                provider_reference=provider_reference,
                timeout_seconds=CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS,
            )
        )


# -- the simulated wire --------------------------------------------------------------------------------


@dataclass
class SimulatedParchmentWire:
    """A well-behaved provider for CI and local runs: idempotent on the key, scriptable, recording.

    `script` answers successive `create` calls (then `ACCEPTED` for the rest). A key it has already
    accepted is answered with the same reference and creates nothing new, which is the property the
    real provider must be confirmed to have (D-012 open item 1). It sends nothing anywhere.
    """

    script: list[WireAnswer] = field(default_factory=list)
    created: dict[str, str] = field(default_factory=dict)
    payloads: list[ParchmentPayload] = field(default_factory=list)
    status_answer: WireAnswer | None = None

    def create(
        self, payload: ParchmentPayload, *, idempotency_key: str, timeout_seconds: float
    ) -> WireAnswer:
        assert timeout_seconds > 0
        self.payloads.append(payload)
        if idempotency_key in self.created:
            return WireAnswer(
                "ACCEPTED", provider_reference=self.created[idempotency_key]
            )
        answer = self.script.pop(0) if self.script else WireAnswer("ACCEPTED")
        if answer.kind == "ACCEPTED":
            reference = (
                answer.provider_reference or f"SIM-{uuid.uuid4().hex[:12].upper()}"
            )
            self.created[idempotency_key] = reference
            return WireAnswer(
                "ACCEPTED",
                provider_reference=reference,
                token_reference=f"TOKEN-{reference}",
            )
        if answer.kind == "UNKNOWN" and answer.provider_reference:
            # The provider created it but the answer was lost: reconciliation should find it.
            self.created[idempotency_key] = answer.provider_reference
            return WireAnswer("UNKNOWN", error_class=answer.error_class)
        return answer

    def status(
        self,
        *,
        idempotency_key: str,
        provider_reference: str | None,
        timeout_seconds: float,
    ) -> WireAnswer:
        if self.status_answer is not None:
            return self.status_answer
        if idempotency_key in self.created:
            return WireAnswer(
                "ACCEPTED", provider_reference=self.created[idempotency_key]
            )
        return WireAnswer("NOT_FOUND", error_class="NOT_FOUND_AT_PROVIDER")
