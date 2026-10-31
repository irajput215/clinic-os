"""Patient intake routes (docs3 feature 03): the applications queue, the doctor's briefing, a
patient's consents and pharmacy, and the pharmacy directory. The public form is served beside the other
public booking routes (`app.modules.appointments.router`).

Tenant from the session (INV-1); `404` across tenants; every refusal raised by the central policy.
"""

import uuid
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ActorDep
from app.core.rate_limit import admin_rate_limit, read_rate_limit
from app.modules.intake import service
from app.modules.intake.schemas import (
    ApplicationCard,
    ApplicationDetail,
    ConsentRecord,
    IntakeBriefing,
    PharmacyCreate,
    PharmacyRead,
    PreferredPharmacy,
    RejectBody,
)
from app.modules.patients import service as patients
from app.modules.patients.schemas import PatientRead
from app.modules.users_roles.policy import enforce
from app.modules.users_roles.service import authorize

router = APIRouter(prefix="/intake-applications", tags=["intake"])
patient_router = APIRouter(prefix="/patients", tags=["intake"])
pharmacies_router = APIRouter(prefix="/pharmacies", tags=["intake"])

_READ = "patient:read"
_CREATE = "patient:create"
_UPDATE = "patient:update"


def _raise(refused: service.IntakeRefused) -> NoReturn:
    raise HTTPException(
        status_code=refused.status_code,
        detail={"code": refused.code, "message": refused.message},
    )


def _raise_patient(refused: service.Refused) -> NoReturn:
    if refused.decision is not None:
        enforce(refused.decision)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
    )


@router.get(
    "", response_model=list[ApplicationCard], dependencies=[Depends(read_rate_limit)]
)
def list_applications(
    *,
    actor: ActorDep,
    application_status: Annotated[
        Literal["SUBMITTED", "ACCEPTED", "REJECTED"], Query(alias="status")
    ] = "SUBMITTED",
) -> list[ApplicationCard]:
    """Patients > Online applications: the queue, oldest first (manual §5.4)."""
    authorize(actor, _READ)
    return service.list_applications(actor=actor, status=application_status)


@router.get(
    "/{application_id}",
    response_model=ApplicationDetail,
    dependencies=[Depends(read_rate_limit)],
)
def read_application(
    *, actor: ActorDep, application_id: uuid.UUID
) -> ApplicationDetail:
    """One application in full: the answers, consents, pharmacy and declaration. Audited."""
    authorize(actor, _READ)
    detail = service.read_application(actor=actor, application_id=application_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": service.APPLICATION_NOT_FOUND,
                "message": "Application not found",
            },
        )
    return detail


@router.post("/{application_id}/accept", dependencies=[Depends(admin_rate_limit)])
def accept_application(
    *, actor: ActorDep, application_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """Accept: consents filed, pharmacy set, a new record made `CURRENT`. `409` if already decided."""
    authorize(actor, _CREATE)
    try:
        patient_id = service.accept(actor=actor, application_id=application_id)
    except service.IntakeRefused as refused:
        _raise(refused)
    return {"patient_id": patient_id}


@router.post(
    "/{application_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(admin_rate_limit)],
)
def reject_application(
    *, actor: ActorDep, application_id: uuid.UUID, body: RejectBody
) -> None:
    """Reject with a reason: the held booking is cancelled, a record it created is archived."""
    authorize(actor, _CREATE)
    try:
        service.reject(actor=actor, application_id=application_id, body=body)
    except service.IntakeRefused as refused:
        _raise(refused)


@patient_router.get(
    "/{patient_id}/intake-briefing",
    response_model=IntakeBriefing | None,
    dependencies=[Depends(read_rate_limit)],
)
def read_intake_briefing(
    *, actor: ActorDep, patient_id: uuid.UUID
) -> IntakeBriefing | None:
    """The doctor's briefing from the patient's own answers; `null` when they never applied online.

    `clinical_record:read` under the treating-relationship rule (D-007). Never shown to the patient.
    """
    authorize(actor, "clinical_record:read")
    result = service.briefing(actor=actor, patient_id=patient_id)
    if isinstance(result, service.Refused):
        _raise_patient(result)
    return result


@patient_router.get(
    "/{patient_id}/consents",
    response_model=list[ConsentRecord],
    dependencies=[Depends(read_rate_limit)],
)
def list_patient_consents(
    *, actor: ActorDep, patient_id: uuid.UUID
) -> list[ConsentRecord]:
    """Which version of each consent the patient agreed to, when, and whether it is current."""
    authorize(actor, _READ)
    result = service.consents(actor=actor, patient_id=patient_id)
    if isinstance(result, service.Refused):
        _raise_patient(result)
    return result


@patient_router.post("/{patient_id}/pharmacy", response_model=PatientRead)
def set_patient_pharmacy(
    *, actor: ActorDep, patient_id: uuid.UUID, body: PreferredPharmacy
) -> PatientRead:
    """Change the patient's pharmacy (manual §3.5). Future scripts default to it. Audited."""
    authorize(actor, _UPDATE)
    if body.pharmacy_id is not None and body.pharmacy_id not in {
        p.id for p in service.list_pharmacies(actor=actor)
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": service.PHARMACY_NOT_FOUND,
                "message": "Choose a pharmacy from the directory.",
            },
        )
    result = patients.set_preferred_pharmacy(
        actor=actor, patient_id=patient_id, pharmacy_id=body.pharmacy_id
    )
    if isinstance(result, patients.PatientRefusal):
        if result.decision is not None:
            enforce(result.decision)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found"
        )
    return result


@pharmacies_router.get(
    "", response_model=list[PharmacyRead], dependencies=[Depends(read_rate_limit)]
)
def list_pharmacies(*, actor: ActorDep) -> list[PharmacyRead]:
    """The clinic's pharmacy directory (manual §8.1)."""
    authorize(actor, _READ)
    return service.list_pharmacies(actor=actor)


@pharmacies_router.post(
    "",
    response_model=PharmacyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(admin_rate_limit)],
)
def create_pharmacy(*, actor: ActorDep, body: PharmacyCreate) -> PharmacyRead:
    """Add a pharmacy. A partner is offered on the public application. Audited."""
    authorize(actor, _UPDATE)
    return service.create_pharmacy(actor=actor, body=body)
