"""The dashboard service facade: the Today page in one tenant transaction.

Contract: `docs2/sdlc/08-today/api.md` (built 2026-10-08, Milestone 2 phase 2E). Rules:

- **No table of its own, and no query of another module's table.** Every section is read through the
  owning module's facade (`appointments.service.day_schedule`,
  `prescriptions.service.queue_summary`, `tga_approvals.service.needs_action_digest`), each taking
  this module's session, so the build contract's module map (section 7) holds.
- **One `tenant_transaction`**, opened with the resolved tenant and the actor, so RLS bounds every
  row and every section agrees on "today" (`now()` is the transaction's start time; the date is
  Australia/Sydney's, R7 and D-006).
- **A section is read only when the caller may read it.** The router decides from the permission
  set; a withheld section is never queried, so it cannot leak through a bug in the response shaping.
- **Audit**: each section is audited exactly as the owning module audits its own list route, on this
  transaction. The approvals section writes `tga_approval.read` (the register's event). The schedule
  and the script queue write nothing, like `GET /appointments` (deferred with `patient.read`, T1-34)
  and `GET /prescriptions` (the closed catalogue has no prescription read action). No catalogue
  action was added; the gap is recorded in `docs2/sdlc/08-today/api.md`.
"""

from collections.abc import Collection
from typing import Final

from app.core.db import tenant_transaction
from app.modules.appointments import service as appointments
from app.modules.dashboard.schemas import DashboardSection, TodaySummary
from app.modules.prescriptions import service as prescriptions
from app.modules.tga_approvals import service as tga_approvals
from app.modules.users_roles.policy import Actor

#: The staging queue card shows at most eight scripts (R3).
SCRIPT_QUEUE_LIMIT: Final[int] = 8
#: Each approvals list is bounded; the counts are the practice's totals.
APPROVAL_DIGEST_LIMIT: Final[int] = 10

SECTIONS: Final[tuple[DashboardSection, ...]] = ("appointments", "scripts", "approvals")


def today(
    *,
    actor: Actor,
    readable: Collection[DashboardSection],
    client_tenant_id_supplied: bool = False,
) -> TodaySummary:
    """Read the sections in `readable`, and name every other section as withheld."""
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        day = appointments.clinic_today(session)
        return TodaySummary(
            date=day,
            timezone=appointments.TIMEZONE,
            appointments=appointments.day_schedule(
                session, tenant_id=actor.tenant_id, day=day
            )
            if "appointments" in readable
            else None,
            scripts=prescriptions.queue_summary(
                session, tenant_id=actor.tenant_id, limit=SCRIPT_QUEUE_LIMIT
            )
            if "scripts" in readable
            else None,
            approvals=tga_approvals.needs_action_digest(
                session,
                tenant_id=actor.tenant_id,
                limit=APPROVAL_DIGEST_LIMIT,
                client_tenant_id_supplied=client_tenant_id_supplied,
            )
            if "approvals" in readable
            else None,
            withheld=[section for section in SECTIONS if section not in readable],
        )
