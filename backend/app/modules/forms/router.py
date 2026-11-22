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
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.forms import service
from app.modules.forms.schemas import (
    AcknowledgeRequest,
    ClinicFormRead,
    ClinicFormResponseCreate,
    ClinicFormResponseRead,
    ClinicFormWrite,
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


# -- clinic-made forms (R6) ----------------------------------------------------------------------
#
# | Method and path | Permission | Audit |
# | --- | --- | --- |
# | `GET /api/v1/clinic-forms` | `clinical_record:read` (active); `tenant:configure` sees retired too | none |
# | `POST /api/v1/clinic-forms` | `tenant:configure` | `form.publish` |
# | `POST /api/v1/clinic-forms/{id}/versions` | `tenant:configure` | `form.publish` |
# | `POST /api/v1/clinic-forms/{id}/retire` | `tenant:configure` | `form.retire` |
# | `POST /api/v1/patients/{id}/clinic-form-responses` | `clinical_record:write` + care relationship | `form_response.create` |


@router.get("/clinic-forms", response_model=list[ClinicFormRead])
def clinic_forms(
    *, actor: ActorDep, include_retired: bool = False
) -> list[ClinicFormRead]:
    _authorize(actor, service.READ_PERMISSION, None)
    if include_retired:
        _authorize(actor, service.CONFIGURE, None)
    return service.list_clinic_forms(actor=actor, include_retired=include_retired)


@router.post(
    "/clinic-forms",
    response_model=ClinicFormRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def create_clinic_form(*, actor: ActorDep, body: ClinicFormWrite) -> ClinicFormRead:
    _authorize(actor, service.CONFIGURE, service.PUBLISH_FORM)
    return service.create_clinic_form(actor=actor, body=body)


@router.post(
    "/clinic-forms/{form_id}/versions",
    response_model=ClinicFormRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def publish_clinic_form_version(
    *, actor: ActorDep, form_id: uuid.UUID, body: ClinicFormWrite
) -> ClinicFormRead:
    _authorize(actor, service.CONFIGURE, service.PUBLISH_FORM)
    result = service.publish_clinic_form_version(
        actor=actor, form_id=form_id, body=body
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Form not found")
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/clinic-forms/{form_id}/retire",
    response_model=ClinicFormRead,
    dependencies=[Depends(admin_rate_limit)],
)
def retire_clinic_form(*, actor: ActorDep, form_id: uuid.UUID) -> ClinicFormRead:
    _authorize(actor, service.CONFIGURE, service.RETIRE_FORM)
    result = service.retire_clinic_form(actor=actor, form_id=form_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return result


@router.post(
    "/patients/{patient_id}/clinic-form-responses",
    response_model=ClinicFormResponseRead,
    status_code=status.HTTP_201_CREATED,
)
def record_clinic_form_response(
    *, actor: ActorDep, patient_id: uuid.UUID, body: ClinicFormResponseCreate
) -> ClinicFormResponseRead:
    _authorize(actor, service.WRITE, service.CREATE)
    result = service.record_clinic_response(
        actor=actor, patient_id=patient_id, body=body
    )
    if isinstance(result, Refusal):
        _raise(result)
    return result
