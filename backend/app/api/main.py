from fastapi import APIRouter

from app.api.routes import health, login, users, utils
from app.modules.audit.router import router as audit_router
from app.modules.patients.router import router as patients_router
from app.modules.users_roles.router import (
    permissions_router,
    roles_router,
    user_roles_router,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(patients_router)
api_router.include_router(roles_router)
api_router.include_router(permissions_router)
api_router.include_router(user_roles_router)
api_router.include_router(audit_router)
