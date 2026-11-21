"""The identities a Parchment request needs, read through each owning module's facade (D-012 §3).

The prescriptions module does not read `patients`, `practitioner_identifiers` or `tga_approvals`
directly (`docs/reference/build-contract.md` §7): each owner answers through its service. The read runs
in its own tenant transaction, scoped by RLS to the prescription's tenant, outside the send.

A missing piece is an `IdentityGap` with codes (`IHI`, `ADDRESS`, `HPI_I`, ...), never a value, and the
adapter refuses before anything is built.
"""

from app.core.db import tenant_transaction
from app.modules.patients import service as patients
from app.modules.prescriptions.transport import DispatchRequest
from app.modules.prescriptions.transports.parchment import (
    DispatchIdentities,
    IdentityGap,
    PatientIdentity,
    PrescriberIdentity,
)
from app.modules.tga_approvals import service as approvals
from app.modules.users_roles import onboarding

SYSTEM_ROLE = "SYSTEM_OUTBOX"


def load_dispatch_identities(
    request: DispatchRequest,
) -> DispatchIdentities | IdentityGap:
    with tenant_transaction(
        tenant_id=request.tenant_id, actor_role=SYSTEM_ROLE
    ) as session:
        patient = patients.escript_patient(
            session, tenant_id=request.tenant_id, patient_id=request.patient_id
        )
        prescriber = onboarding.escript_prescriber(
            session, tenant_id=request.tenant_id, user_id=request.prescriber_id
        )
        reference = approvals.approval_reference(
            session, tenant_id=request.tenant_id, approval_id=request.approval_id
        )
    missing: list[str] = []
    if patient is None:
        missing.append("PATIENT")
    else:
        missing.extend(patient.missing)
    if prescriber is None:
        missing.append("PRESCRIBER")
    else:
        missing.extend(prescriber.missing)
    if reference is None:
        missing.append("APPROVAL")
    if missing or patient is None or prescriber is None or reference is None:
        return IdentityGap(tuple(dict.fromkeys(missing)))
    # `escript_readiness` has already required these; the asserts make the types say so.
    assert patient.ihi and patient.sex and patient.address_line and patient.suburb
    assert patient.state and patient.postcode
    assert prescriber.hpi_i and prescriber.prescriber_number
    return DispatchIdentities(
        prescriber=PrescriberIdentity(
            full_name=prescriber.full_name,
            hpi_i=prescriber.hpi_i,
            prescriber_number=prescriber.prescriber_number,
        ),
        patient=PatientIdentity(
            given_name=patient.given_name,
            family_name=patient.family_name,
            date_of_birth=patient.date_of_birth,
            sex=patient.sex,
            ihi=patient.ihi,
            address_line=patient.address_line,
            suburb=patient.suburb,
            state=patient.state,
            postcode=patient.postcode,
            medicare_number=patient.medicare_number,
            medicare_irn=patient.medicare_irn,
        ),
        tga_approval_reference=reference,
    )
