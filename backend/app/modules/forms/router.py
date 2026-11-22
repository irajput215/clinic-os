"""Questionnaire routes (docs3 Phase 6 feature 05).

| Method and path | Permission | Notes | Audit |
| --- | --- | --- | --- |
| `GET /api/v1/forms/instruments` | `clinical_record:read` | the three definitions and the acknowledge actions; no patient data | none |
| `GET /api/v1/patients/{id}/form-responses` | `clinical_record:read` + care relationship | history newest first and open flags | `form_response.read` |
| `POST /api/v1/patients/{id}/form-responses` | `clinical_record:write` + care relationship | scores, stores, raises flags in one transaction | `form_response.create`, `safety_flag.raise` |
| `POST /api/v1/safety-flags/{id}/acknowledge` | `clinical_record:write` + care relationship | action code from the closed list | `safety_flag.acknowledge` |

`404`, never `403`, across clinics. No body carries a tenant, patient, score, band or author.
"""

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import ActorDep
from app.core.rate_limit import read_rate_limit
from app.modules.forms import service
from app.modules.forms.schemas import (
    AcknowledgeRequest,
    FormResponseCreate,
    FormResponseRead,
    InstrumentCatalogue,
    PatientForms,
    SafetyFlagRead,
)
from app.modules.forms.service import Refusal
from app.modules.users_roles.policy import Actor, can, enforce

router = APIRouter(tags=["forms"])


def _authorize(actor: Actor, permission: str, action: str | None) -> None:
    decision = can(actor, permission)
    if not decision.allowed and action is not None:
        service.audit_denial(actor=actor, action=action, reason=decision.code.value)
    enforce(decision)


def _raise(refusal: Refusal) -> NoReturn:
    if refusal.decision is not None:
        enforce(refusal.decision)
    if refusal.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status_code=404, detail="Patient not found")
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


@router.get("/forms/instruments", response_model=InstrumentCatalogue)
def instruments(*, actor: ActorDep) -> InstrumentCatalogue:
    _authorize(actor, service.READ_PERMISSION, None)
    return service.catalogue()


@router.get(
    "/patients/{patient_id}/form-responses",
    response_model=PatientForms,
    dependencies=[Depends(read_rate_limit)],
)
def patient_form_responses(*, actor: ActorDep, patient_id: uuid.UUID) -> PatientForms:
    _authorize(actor, service.READ_PERMISSION, service.READ)
    result = service.patient_forms(actor=actor, patient_id=patient_id)
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/patients/{patient_id}/form-responses",
    response_model=FormResponseRead,
    status_code=status.HTTP_201_CREATED,
)
def record_form_response(
    *, actor: ActorDep, patient_id: uuid.UUID, body: FormResponseCreate
) -> FormResponseRead:
    _authorize(actor, service.WRITE, service.CREATE)
    result = service.record_response(actor=actor, patient_id=patient_id, body=body)
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post("/safety-flags/{flag_id}/acknowledge", response_model=SafetyFlagRead)
def acknowledge_safety_flag(
    *, actor: ActorDep, flag_id: uuid.UUID, body: AcknowledgeRequest
) -> SafetyFlagRead:
    _authorize(actor, service.WRITE, service.ACKNOWLEDGE)
    result = service.acknowledge_flag(
        actor=actor, flag_id=flag_id, action_code=body.action_code
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Safety flag not found")
    if isinstance(result, Refusal):
        _raise(result)
    return result
