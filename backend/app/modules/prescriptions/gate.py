"""The prescription safety gate: the one function that may say "this prescription is covered".

`docs/features/10-prescription-safety-gate/` (INV-2): no prescription is signed or released without an
`ACTIVE`, verified TGA approval for the same patient, TGA category and dosage form whose window covers
`date_of_service` - half-open `[valid_from, valid_to)`, the D-006 interim, decided by
`tga_approvals.service.within_validity_window` and nowhere else.

Rules this module holds to, each checked by a static test in `tests/prescriptions/test_static.py`:

1. **One deciding entry point**, `decide`. The signing route, the dispatch route and the outbox
   worker call it; nothing else in the code base reaches `tga_approvals.service.evaluate_match` with
   `lock=True`.
2. **No escape hatch.** `decide` takes the session and the prescription row, and nothing that could
   turn it off: the token search for the usual bypass words finds nothing in this file.
3. **Inside the caller's transaction, with the rows locked.** `decide` reads every approval of the
   patient `FOR UPDATE` on the transaction that will write the state change, so a concurrent
   revocation either commits first (and is seen) or waits until this decision has committed.
4. **Fail closed.** Any error in the lookup propagates and rolls the caller's transaction back: no
   decision is a refusal.

`advise_many` is the read-only counterpart for the queue's display. It never authorises anything: it
holds no lock, its answer is never written, and every action re-asks `decide`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import Session

from app.core.reads import Pending, ReadBatch
from app.modules.prescriptions.models import Prescription
from app.modules.tga_approvals import service as tga_approvals
from app.modules.tga_approvals.schemas import TgaMatchResponse

# The user-facing sentence for a refusal (FEAT-10 design, steps 7 and 8). The machine-readable reason
# is the match's own closed vocabulary (`tga_approvals.service.MatchReason`).
REFUSAL_MESSAGE = "Active TGA Approval Required"


@dataclass(frozen=True)
class GateDecision:
    """The gate's answer. `approval_id` is the covering approval when allowed."""

    allowed: bool
    reason_code: str | None
    approval_id: uuid.UUID | None
    match: TgaMatchResponse


def _ask(
    session: Session, prescription: Prescription, *, lock: bool
) -> TgaMatchResponse:
    return tga_approvals.evaluate_match(
        session,
        tenant_id=prescription.tenant_id,
        patient_id=prescription.patient_id,
        tga_category=prescription.tga_category,
        dosage_form=prescription.dosage_form,
        date_of_service=prescription.date_of_service,
        lock=lock,
    )


def decide(session: Session, prescription: Prescription) -> GateDecision:
    """The deciding evaluation, with the approval rows locked until the caller's transaction ends."""
    match = _ask(session, prescription, lock=True)
    allowed = (
        match.matched and match.approval_id is not None and match.state == "ACTIVE"
    )
    return GateDecision(
        allowed=allowed,
        reason_code=None
        if allowed
        else (match.reason_code or "TGA_APPROVAL_NOT_FOUND"),
        approval_id=match.approval_id if allowed else None,
        match=match,
    )


def advise_many(
    batch: ReadBatch, prescriptions: Sequence[Prescription]
) -> Pending[dict[uuid.UUID, TgaMatchResponse]]:
    """The gate's current answer for each prescription, for display only: no lock, never an
    authorisation.

    Queued on the caller's batch (`app.core.reads`), so a whole queue is answered by one read of the
    patients' approvals rather than one read per prescription. Each answer is the same match
    `decide` evaluates, minus the lock; signing and dispatch re-ask `decide` on their own
    transaction.
    """
    if not prescriptions:
        return Pending.ready({})
    [tenant_id] = {prescription.tenant_id for prescription in prescriptions}
    answers = tga_approvals.queue_matches(
        batch,
        tenant_id=tenant_id,
        questions=[
            tga_approvals.MatchQuestion(
                patient_id=prescription.patient_id,
                tga_category=prescription.tga_category,
                dosage_form=prescription.dosage_form,
                date_of_service=prescription.date_of_service,
            )
            for prescription in prescriptions
        ],
    )
    return answers.then(
        lambda found: {
            prescription.id: answer
            for prescription, answer in zip(prescriptions, found, strict=True)
        }
    )
