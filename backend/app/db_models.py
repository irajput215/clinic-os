"""The model registry.

Alembic reads `SQLModel.metadata`, so every table must be imported somewhere on
that path. This module is that single place: `alembic/env.py` imports it, and
nothing else has to remember to import a model for its table to exist.

Importing it also applies the naming convention from `app.core.metadata` before
any table is defined.
"""

from sqlmodel import SQLModel

from app.core.metadata import NAMING_CONVENTION
from app.models import User
from app.modules.appointments.models import Appointment, AppointmentSettings
from app.modules.audit.models import AuditLogEntry
from app.modules.care_relationships.models import CareRelationship
from app.modules.clinical_records.models import (
    ClinicalRecord,
    ClinicalRecordVersion,
)
from app.modules.clinics.models import Clinic
from app.modules.identity_tenancy.models import Tenant
from app.modules.patients.models import Patient
from app.modules.tga_approvals.models import TgaApproval, TgaApprovalEvent
from app.modules.users_roles.models import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)

__all__ = [
    "NAMING_CONVENTION",
    "SQLModel",
    "Appointment",
    "AppointmentSettings",
    "AuditLogEntry",
    "CareRelationship",
    "Clinic",
    "ClinicalRecord",
    "ClinicalRecordVersion",
    "Patient",
    "Permission",
    "Role",
    "RolePermission",
    "Tenant",
    "TgaApproval",
    "TgaApprovalEvent",
    "User",
    "UserRole",
]
