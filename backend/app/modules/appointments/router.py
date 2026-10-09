"""The appointments HTTP API: the calendar (staff) and the public booking page (unauthenticated).

Contract: `docs2/sdlc/04-calendar-and-booking/api.md`, agreed 2026-10-07 by the owner, who also
approved the two unauthenticated public routes. Requirements: the same folder's `requirements.md`.

Staff routes follow the request path every module does: authenticate -> resolve the tenant from the
session (`get_actor`, INV-1) -> authorise through the central policy layer -> validate a strict body ->
execute inside the RLS-scoped transaction, audited on the same transaction.

The public routes have no session, so the order is: rate-limit (per address, and per email for a
booking) -> resolve the tenant **server-side** from the slug (only an `ACTIVE` organisation; anything
else is the same `404`) -> validate -> execute under that tenant's RLS context, audited. The slug is
routing only: it selects which clinic's free slots are read and grants nothing else - no patient, no
appointment and no staff detail beyond a practitioner's display name ever leaves these routes.

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

| Method and path | Auth | Permission | Tenant scope | Input | Output | Audit |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /practitioners` | yes | `patient:read` | session | none | `PractitionerRead[]` | none (a read of staff names) |
| `GET /appointments?from=&to=&practitioner_id=` | yes | `patient:read` | session | query | `AppointmentRead[]` | deferred with `patient.read` (T1-34) |
| `POST /appointments` | yes | `patient:update` | session | `AppointmentCreate` | `AppointmentRead` (201) | `appointment.create` |
| `POST /appointments/{id}/status` | yes | `patient:update` | both | `AppointmentStatusUpdate` | `AppointmentRead` | `appointment.state_change` |
| `GET /patients/{id}/appointments` | yes | `patient:read` | both | none | `AppointmentRead[]` | deferred with `patient.read` (T1-34) |
| `GET /public/{slug}` | **no** | none | slug, server-side | none | `PublicClinicRead` (`display_name` only) | none (PUBLIC data only) |
| `GET /public/{slug}/slots?type=` | **no** | none | slug, server-side | query | `PublicSlot[]` | none (no personal data read) |
| `POST /public/{slug}/bookings` | **no** | none | slug, server-side | `PublicBookingRequest` (JSON only) | `{reference}` (201) | `patient.create` (when new), `appointment.create` |
| `GET /appointment-settings` | yes | none (PUBLIC hours; any member) | session | none | `AppointmentSettingsRead` | none |
| `PUT /appointment-settings` | yes | `tenant:configure` | session | `AppointmentSettingsUpdate` | `AppointmentSettingsSaved` | `tenant.config_changed` (and `DENIED` for a refusal) |
| `POST /internal/booking-notifications/run` | bearer job token (off when unset: `404`) | none | each active tenant, server-side | none | `NotificationRunReport` | `integration.request` per email sent |

A `tenant_id` in a body or a query string is never read: it is ignored and recorded as
`appointment.create` `DENIED` `CLIENT_TENANT_ID_IGNORED` (INV-1). Errors are RFC 7807 with
`detail.code`; another tenant's appointment, patient or practitioner is `404`, never `403`.
"""

import hashlib
import hmac
import re
import uuid
from typing import Annotated, Any, NoReturn

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import AwareDatetime

from app.api.deps import ActorDep, SessionDep
from app.core.config import settings
from app.core.rate_limit import (
    PUBLIC_BOOKING_EMAIL_LIMIT,
    PUBLIC_BOOKING_EMAIL_WINDOW_SECONDS,
    admin_rate_limit,
    internal_job_rate_limit,
    limit_identifier,
    public_booking_rate_limit,
    public_slots_rate_limit,
    read_rate_limit,
)
from app.modules.appointments import notifications, service
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentSettingsRead,
    AppointmentSettingsSaved,
    AppointmentSettingsUpdate,
    AppointmentStatusUpdate,
    AppointmentType,
    NotificationRunReport,
    PractitionerRead,
    PublicBookingCreated,
    PublicBookingRequest,
    PublicSlot,
)
from app.modules.identity_tenancy import service as identity_tenancy
from app.modules.identity_tenancy.schemas import PublicClinicRead
from app.modules.users_roles.catalog import (
    APPOINTMENT_PERMISSIONS,
    EMAIL_NOT_CONFIGURED,
    TENANCY_PERMISSIONS,
)
from app.modules.users_roles.policy import ResourceRef, enforce
from app.modules.users_roles.service import authorize, can

practitioners_router = APIRouter(prefix="/practitioners", tags=["appointments"])
router = APIRouter(prefix="/appointments", tags=["appointments"])
patient_router = APIRouter(prefix="/patients", tags=["appointments"])
public_router = APIRouter(prefix="/public", tags=["public-booking"])
settings_router = APIRouter(prefix="/appointment-settings", tags=["appointments"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])

# The shape `identity_tenancy.service.slugify` produces. Anything else cannot be a clinic, and is
# answered exactly like an unknown clinic.
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {"description": "Absent, or another organisation's"},
    409: {
        "description": "Refused by the booking rules (overlap, slot taken, illegal transition)"
    },
}


def _raise(refusal: service.AppointmentRefused) -> NoReturn:
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    ) from None


def _client_address(request: Request) -> str | None:
    return request.client.host if request.client else None


# -- staff -----------------------------------------------------------------------------------------


@practitioners_router.get("", response_model=list[PractitionerRead])
def list_practitioners(*, actor: ActorDep) -> list[PractitionerRead]:
    """Bookable staff: active accounts holding a Doctor, Authorised Prescriber or Nurse role."""
    authorize(actor, APPOINTMENT_PERMISSIONS["read"])
    return service.list_practitioners(tenant_id=actor.tenant_id)


@router.get("", response_model=list[AppointmentRead], responses=_REFUSALS)
def list_appointments(
    *,
    actor: ActorDep,
    request: Request,
    starts_from: Annotated[AwareDatetime, Query(alias="from")],
    starts_before: Annotated[AwareDatetime, Query(alias="to")],
    practitioner_id: uuid.UUID | None = None,
) -> list[AppointmentRead]:
    """Appointments starting in `[from, to)`, at most 31 days, earliest first."""
    authorize(actor, APPOINTMENT_PERMISSIONS["read"])
    try:
        return service.list_appointments(
            actor=actor,
            starts_from=starts_from,
            starts_before=starts_before,
            practitioner_id=practitioner_id,
            source_ip=_client_address(request),
        )
    except service.AppointmentRefused as refusal:
        _raise(refusal)


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=_REFUSALS,
)
def create_appointment(
    *,
    actor: ActorDep,
    body: AppointmentCreate,
    request: Request,
    background_tasks: BackgroundTasks,
) -> AppointmentRead:
    """Book a patient with a practitioner. `409 APPOINTMENT_OVERLAP` names the clash's time.

    The patient's confirmation email is sent after the booking commits (when email is configured).
    """
    authorize(actor, APPOINTMENT_PERMISSIONS["write"])
    if body.client_tenant_id_supplied or "tenant_id" in request.query_params:
        service.record_client_tenant_id_ignored(
            tenant_id=actor.tenant_id,
            actor_id=actor.user_id,
            actor_role=actor.actor_role,
        )
    try:
        created = service.create_appointment(actor=actor, body=body)
    except service.AppointmentRefused as refusal:
        _raise(refusal)
    background_tasks.add_task(
        notifications.send_confirmation,
        tenant_id=actor.tenant_id,
        appointment_id=created.id,
    )
    return created


@router.post(
    "/{appointment_id}/status", response_model=AppointmentRead, responses=_REFUSALS
)
def change_appointment_status(
    *, actor: ActorDep, appointment_id: uuid.UUID, body: AppointmentStatusUpdate
) -> AppointmentRead:
    """Move a booking through its states. `409 ILLEGAL_STATE_TRANSITION` outside R4's table."""
    authorize(
        actor, APPOINTMENT_PERMISSIONS["write"], ResourceRef(tenant_id=actor.tenant_id)
    )
    try:
        return service.change_status(
            actor=actor, appointment_id=appointment_id, status=body.status
        )
    except service.AppointmentRefused as refusal:
        _raise(refusal)


@patient_router.get(
    "/{patient_id}/appointments",
    response_model=list[AppointmentRead],
    responses=_REFUSALS,
)
def list_patient_appointments(
    *, actor: ActorDep, request: Request, patient_id: uuid.UUID
) -> list[AppointmentRead]:
    """One patient's bookings, newest first. Another tenant's patient is `404`; one of this
    organisation's without the care relationship a doctor's or nurse's grant needs is `403`."""
    authorize(
        actor, APPOINTMENT_PERMISSIONS["read"], ResourceRef(tenant_id=actor.tenant_id)
    )
    result = service.list_for_patient(
        actor=actor, patient_id=patient_id, source_ip=_client_address(request)
    )
    if not result.found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": service.PATIENT_NOT_FOUND, "message": "Patient not found"},
        )
    if result.decision is not None:
        enforce(result.decision)
    return result.bookings


# -- public ----------------------------------------------------------------------------------------


def _clinic(session: SessionDep, clinic_slug: str) -> uuid.UUID:
    """The tenant behind a slug, resolved on the server. Unknown, malformed or not active: `404`."""
    tenant_id = (
        identity_tenancy.active_tenant_id_for_slug(session, clinic_slug)
        if _SLUG.match(clinic_slug)
        else None
    )
    if tenant_id is None:
        raise _clinic_not_found()
    return tenant_id


def _clinic_not_found() -> HTTPException:
    """One answer for an unknown, malformed or inactive clinic, so none is distinguishable."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "CLINIC_NOT_FOUND",
            "message": "This booking page isn't available.",
        },
    )


def _json_only(request: Request) -> None:
    """A booking is accepted as `application/json` and nothing else.

    A cross-site form can only send `application/x-www-form-urlencoded`, `multipart/form-data` or
    `text/plain` without a CORS preflight, so refusing every other type makes the route CSRF-safe by
    construction - on top of it carrying no ambient authority (no cookie, no session) to forge.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": "Send the booking as application/json.",
            },
        )


ClinicDep = Annotated[uuid.UUID, Depends(_clinic)]


@public_router.get(
    "/{clinic_slug}",
    response_model=PublicClinicRead,
    dependencies=[Depends(public_slots_rate_limit)],
    responses={404: {"description": "No such clinic, or not taking bookings"}},
)
def read_public_clinic(*, session: SessionDep, clinic_slug: str) -> PublicClinicRead:
    """The clinic's public display name, for the booking page's heading. Unauthenticated.

    Only the PUBLIC display name: never `legal_name`, the tenant id or the status. Resolved like the
    other public routes (only an `ACTIVE` clinic; anything else is the same `404 CLINIC_NOT_FOUND`).
    """
    clinic = (
        identity_tenancy.public_clinic_for_slug(session, clinic_slug)
        if _SLUG.match(clinic_slug)
        else None
    )
    if clinic is None:
        raise _clinic_not_found()
    return clinic


@public_router.get(
    "/{clinic_slug}/slots",
    response_model=list[PublicSlot],
    dependencies=[Depends(public_slots_rate_limit)],
    responses={404: {"description": "No such clinic, or not taking bookings"}},
)
def list_public_slots(
    *,
    tenant_id: ClinicDep,
    appointment_type: Annotated[AppointmentType, Query(alias="type")],
) -> list[PublicSlot]:
    """Free slots for one visit type over the next 14 days. Unauthenticated."""
    return service.public_slots(tenant_id=tenant_id, appointment_type=appointment_type)


@public_router.post(
    "/{clinic_slug}/bookings",
    response_model=PublicBookingCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(public_booking_rate_limit), Depends(_json_only)],
    responses={
        404: {"description": "No such clinic, or not taking bookings"},
        409: {"description": "`SLOT_TAKEN`: somebody booked that time first"},
        415: {"description": "Not `application/json`"},
    },
)
def create_public_booking(
    *,
    tenant_id: ClinicDep,
    body: PublicBookingRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> PublicBookingCreated:
    """Book from the public page. The same answer whether the patient was new or already known."""
    limit_identifier(
        scope="public-booking-email",
        identifier=str(body.email),
        limit=PUBLIC_BOOKING_EMAIL_LIMIT,
        window_seconds=PUBLIC_BOOKING_EMAIL_WINDOW_SECONDS,
    )
    address = _client_address(request)
    if body.client_tenant_id_supplied or "tenant_id" in request.query_params:
        service.record_client_tenant_id_ignored(
            tenant_id=tenant_id, actor_role="PUBLIC_BOOKING", source_ip=address
        )
    try:
        appointment_id = service.public_book(
            tenant_id=tenant_id, body=body, source_ip=address
        )
    except service.AppointmentRefused as refusal:
        _raise(refusal)
    background_tasks.add_task(
        notifications.send_confirmation,
        tenant_id=tenant_id,
        appointment_id=appointment_id,
    )
    return PublicBookingCreated(reference=service.booking_reference(appointment_id))


# -- clinic hours and slot length ------------------------------------------------------------------


@settings_router.get(
    "", response_model=AppointmentSettingsRead, dependencies=[Depends(read_rate_limit)]
)
def read_appointment_settings(*, actor: ActorDep) -> AppointmentSettingsRead:
    """The clinic's hours and slot length, for every member: opening hours are PUBLIC."""
    return service.get_settings(tenant_id=actor.tenant_id)


@settings_router.put(
    "",
    response_model=AppointmentSettingsSaved,
    dependencies=[Depends(admin_rate_limit)],
    responses={
        403: {
            "description": "`PERMISSION_NOT_HELD`: changing the hours needs `tenant:configure`. "
            "Audited; nothing changes."
        }
    },
)
def update_appointment_settings(
    *, actor: ActorDep, body: AppointmentSettingsUpdate, request: Request
) -> AppointmentSettingsSaved:
    """Set the hours per weekday and the slot length (Practice Owner). Audited on its transaction."""
    decision = can(actor, TENANCY_PERMISSIONS["configure"])
    if not decision.allowed:
        service.record_settings_denial(actor=actor, reason=decision.code.value)
        enforce(decision)
    return service.update_settings(
        actor=actor,
        body=body,
        client_tenant_id_supplied=(
            body.client_tenant_id_supplied or "tenant_id" in request.query_params
        ),
    )


# -- the booking-email job (D-009) -----------------------------------------------------------------


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _run_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Off unless configured (`404`, as if absent); otherwise the bearer token, compared in constant
    time over digests so neither its value nor its length leaks through timing."""
    configured = settings.BOOKING_NOTIFICATIONS_RUN_TOKEN
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Not Found"},
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        _digest(supplied), _digest(configured.get_secret_value())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Not authorised."},
            headers={"WWW-Authenticate": "Bearer"},
        )


@internal_router.post(
    "/booking-notifications/run",
    response_model=NotificationRunReport,
    dependencies=[Depends(internal_job_rate_limit), Depends(_run_token)],
    responses={
        401: {"description": "Wrong or missing token"},
        404: {"description": "The job endpoint is not enabled on this server"},
        503: {"description": "`EMAIL_NOT_CONFIGURED`: outgoing email is off"},
    },
)
def run_booking_notifications() -> NotificationRunReport:
    """Send every due booking confirmation and reminder, one tenant at a time. Counts only.

    For a scheduler (D-009). No tenant is named by the caller: the job reads the active tenants and
    runs each in its own transaction. Idempotent: a second call sends nothing the first one sent.
    """
    try:
        return notifications.send_due_for_every_tenant()
    except notifications.EmailNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": EMAIL_NOT_CONFIGURED,
                "message": "Outgoing email is not configured.",
            },
        ) from None
