"""The Today page's response (`docs2/sdlc/08-today/api.md`).

Each section is the owning module's own read model, so a field means the same thing here as on the
screen the section links to. A section the caller holds no read permission for is `null` **and**
named in `withheld`: its data was never read, so it cannot leak, and the screen can say why the
card is missing rather than showing an empty one that looks like "nothing today".
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.modules.appointments.schemas import DaySchedule
from app.modules.prescriptions.schemas import PrescriptionQueueSummary
from app.modules.tga_approvals.schemas import TgaApprovalDigest

DashboardSection = Literal["appointments", "scripts", "approvals"]


class TodaySummary(BaseModel):
    """`GET /api/v1/dashboard/today`: the clinic's day in one read."""

    #: Today in the clinic (`timezone`), from the database clock.
    date: date
    timezone: str
    #: Every booking starting today, earliest first (`patient:read`).
    appointments: DaySchedule | None
    #: The script queue's counts and its newest actionable scripts with the live gate
    #: (`prescription:read`).
    scripts: PrescriptionQueueSummary | None
    #: Approvals waiting for verification, and active ones expiring soon (`tga_approval:read`).
    approvals: TgaApprovalDigest | None
    #: The sections left out because the caller does not hold their read permission.
    withheld: list[DashboardSection]
