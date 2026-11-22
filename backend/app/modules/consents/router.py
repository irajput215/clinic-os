"""Consent library routes (docs3 Phase 6 feature 06).

| Method and path | Permission | Audit |
| --- | --- | --- |
| `GET /api/v1/consents` | `tenant:configure` | none (clinic configuration, no patient data beyond counts) |
| `POST /api/v1/consents/{kind}/versions` | `tenant:configure` | `consent.publish` |
| `GET /api/v1/patients/{id}/consents` | `patient:read` + care relationship | `patient.read` |
| `POST /api/v1/patients/{id}/consents` | `patient:update` + care relationship | `consent.record` |
| `POST /api/v1/patients/{id}/consents/{kind}/withdraw` | `patient:update` + care relationship | `consent.withdraw` |

`GET /patients/{id}/consents` moved here from the intake module, with a richer answer: each kind's
status, not only the list of signatures. `404`, never `403`, across clinics.
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ActorDep
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.consents import service
from app.modules.consents.schemas import (
    ConsentDocumentRead,
    ConsentKind,
    ConsentLibrary,
    PatientConsentStatus,
    PublishConsent,
    RecordConsent,
    WithdrawConsent,
)
from app.modules.consents.service import Refusal
from app.modules.users_roles.policy import Actor, can, enforce

router = APIRouter(tags=["consents"])


def _authorize(actor: Actor, permission: str, action: str | None) -> None:
    decision = can(actor, permission)
    if not decision.allowed and action is not None:
        service.audit_denial(actor=actor, action=action, reason=decision.code.value)
    enforce(decision)


def _answer[T](result: T | Refusal) -> T:
    if isinstance(result, Refusal):
        if result.decision is not None:
            enforce(result.decision)
        if result.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(status_code=404, detail="Patient not found")
        _raise(result)
    return result


def _raise(refusal: Refusal) -> NoReturn:
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


@router.get(
    "/consents", response_model=ConsentLibrary, dependencies=[Depends(read_rate_limit)]
)
def consent_library(*, actor: ActorDep) -> ConsentLibrary:
    """Each consent's current text (the clinic's, or the platform default) and the clinic's versions."""
    _authorize(actor, service.CONFIGURE, None)
    return service.library(actor=actor)


@router.post(
    "/consents/{kind}/versions",
    response_model=ConsentDocumentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def publish_consent(
    *, actor: ActorDep, kind: ConsentKind, body: PublishConsent
) -> ConsentDocumentRead:
    """Publish the clinic's next version. Patients on an older text need to consent again."""
    _authorize(actor, service.CONFIGURE, service.PUBLISH)
    return service.publish(actor=actor, kind=kind, title=body.title, body=body.body)


@router.get(
    "/patients/{patient_id}/consents",
    response_model=PatientConsentStatus,
    dependencies=[Depends(read_rate_limit)],
)
def patient_consents(*, actor: ActorDep, patient_id: uuid.UUID) -> PatientConsentStatus:
    _authorize(actor, service.PATIENT_READ, service.READ)
    return _answer(service.patient_status(actor=actor, patient_id=patient_id))


@router.post("/patients/{patient_id}/consents", response_model=PatientConsentStatus)
def record_consent(
    *, actor: ActorDep, patient_id: uuid.UUID, body: RecordConsent
) -> PatientConsentStatus:
    """A consent given in clinic, at the version currently offered."""
    _authorize(actor, service.PATIENT_UPDATE, service.RECORD)
    return _answer(
        service.record_consent(
            actor=actor, patient_id=patient_id, kind=body.kind, version=body.version
        )
    )


@router.post(
    "/patients/{patient_id}/consents/{kind}/withdraw",
    response_model=PatientConsentStatus,
)
def withdraw_consent(
    *, actor: ActorDep, patient_id: uuid.UUID, kind: ConsentKind, body: WithdrawConsent
) -> PatientConsentStatus:
    """The patient withdrew this consent, effective now."""
    _authorize(actor, service.PATIENT_UPDATE, service.WITHDRAW)
    return _answer(
        service.withdraw(
            actor=actor, patient_id=patient_id, kind=kind, method=body.method
        )
    )
