from fastapi import APIRouter

from app.api.routes import health, login, users, utils
from app.modules.appointments.router import (
    patient_router as appointments_patient_router,
)
from app.modules.appointments.router import (
    practitioners_router,
)
from app.modules.appointments.router import public_router as public_booking_router
from app.modules.appointments.router import router as appointments_router
from app.modules.audit.router import router as audit_router
from app.modules.clinical_records.router import router as clinical_records_router
from app.modules.identity_tenancy.router import router as tenants_router
from app.modules.patients.router import router as patients_router
from app.modules.tga_approvals.router import (
    patient_router as tga_patient_router,
)
from app.modules.tga_approvals.router import router as tga_approvals_router
from app.modules.users_roles.router import (
    current_user_router,
    invitations_router,
    permissions_router,
    roles_router,
    staff_router,
    user_roles_router,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(login.router)
# Before the legacy `users.router`: its `/users/{user_id}` would otherwise capture the literal
# `staff` segment (and answer `422` for a non-UUID id). `test_staff.py` pins the order.
api_router.include_router(staff_router)
api_router.include_router(invitations_router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(patients_router)
api_router.include_router(roles_router)
api_router.include_router(permissions_router)
# Before `user_roles_router`: `/users/me/permissions` must match before `/users/{user_id}/permissions`
# can capture the literal `me` (and answer `422`). `test_own_permissions.py` pins the order.
api_router.include_router(current_user_router)
api_router.include_router(user_roles_router)
api_router.include_router(tenants_router)
api_router.include_router(audit_router)
api_router.include_router(clinical_records_router)
# Feature 08. Two routers, and the second is the design's patient-scoped list path
# (`GET /api/v1/patients/{patient_id}/tga-approvals`), which cannot live under the
# `/tga-approvals` prefix. The patients router is another module's; a module owns its routes.
api_router.include_router(tga_approvals_router)
api_router.include_router(tga_patient_router)
# Feature 04 (calendar and booking, docs2/sdlc/04). The last two are the unauthenticated public
# booking routes: the tenant is resolved from the slug on the server, never from the client.
api_router.include_router(practitioners_router)
api_router.include_router(appointments_router)
api_router.include_router(appointments_patient_router)
api_router.include_router(public_booking_router)
