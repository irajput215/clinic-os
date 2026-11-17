"""The TGA inbox HTTP API (FEAT-09, D-011).

## Endpoint declarations (`docs/reference/definition-of-done.md` §4)

| Method and path | Authentication | Permission | Tenant scope | Input | Output | Audit |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /api/v1/tga-inbox/messages` | mailbox bearer token (off when unset: `404`) | mailbox service role | the `to` address (mailbox identity) | `InboundMessageIn` | `IngestResult` (201) | `tga_document.ingest`, `tga_document.extract` |
| `GET /api/v1/tga-inbox/address` | session | `tga_inbox:process` | session | none | `{address}` | none |
| `GET /api/v1/tga-inbox/messages` | session | `tga_inbox:process` | session | `state`, `limit` | `InboxQueue` | `tga_approval.read` |
| `GET /api/v1/tga-inbox/messages/{id}` | session | `tga_inbox:process` | session + resource | path | `InboxMessageDetail` | `tga_approval.read` |
| `GET /api/v1/tga-inbox/attachments/{id}/content` | session | `tga_inbox:process` | session + resource | path | `application/pdf` | `tga_approval.read` |
| `POST /api/v1/tga-inbox/messages/{id}/claim` | session | `tga_inbox:process` | session + resource | none | `InboxMessageDetail` | none (a lease, not a decision) |
| `POST /api/v1/tga-inbox/messages/{id}/accept` | session | `tga_inbox:process` | session + resource | `AcceptRequest` | `DecisionResult` | `tga_approval.verify`, `tga_approval.create` |
| `POST /api/v1/tga-inbox/messages/{id}/reject` | session | `tga_inbox:process` | session + resource | `RejectRequest` | `DecisionResult` | `tga_approval.verify` |
| `POST /api/v1/tga-inbox/messages/{id}/defer` | session | `tga_inbox:process` | session + resource | none | `DecisionResult` | `tga_approval.verify` |

**One permission, `tga_inbox:process`, for every review route.** The design names `tga_inbox:read` and
`tga_inbox:verify`; the permission catalogue has `tga_inbox:process` only, and adding codes is a
permission-matrix change that needs approval (AGENTS.md). Accept does not activate anything, so the
separation that matters (R14) is held by `tga_approval:verify` on the approval itself.

**Step-up is not required on accept**, because accept creates a `PENDING` approval; the step that
makes it dispensable is the approval's own verify, by a second clinician.

Cross-tenant and absent are one answer, `404` (R23). No route accepts a `tenant_id`, `state`,
`score` or `accepted_by` (strict schemas).
"""

import hashlib
import hmac
import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import ActorDep
from app.core.config import settings
from app.core.rate_limit import rate_limit, read_rate_limit
from app.modules.tga_inbox import pipeline, service
from app.modules.tga_inbox.models import MESSAGE_STATES
from app.modules.tga_inbox.schemas import (
    AcceptRequest,
    DecisionResult,
    InboundMessageIn,
    InboxMessageDetail,
    InboxQueue,
    IngestResult,
    RejectRequest,
)
from app.modules.tga_inbox.service import Refusal
from app.modules.users_roles.policy import Actor, can, enforce

PROCESS = "tga_inbox:process"

router = APIRouter(prefix="/tga-inbox", tags=["tga-inbox"])

ingest_rate_limit = rate_limit(scope="tga-inbox-ingest", limit=120, window_seconds=60)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _ingest_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Off unless configured (`404`, as if absent); otherwise the bearer token in constant time."""
    configured = settings.TGA_INBOX_INGEST_TOKEN
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


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Inbox message not found"
    )


def _raise(refusal: Refusal) -> NoReturn:
    raise HTTPException(
        status_code=refusal.status_code,
        detail={"code": refusal.code, "message": refusal.message},
    )


def _authorize(actor: Actor, *, action: str) -> None:
    """Decide, audit a refusal, then enforce (deny-by-default path step 4)."""
    decision = can(actor, PROCESS)
    if not decision.allowed:
        service.audit_denial(actor=actor, action=action, reason=decision.code.value)
    enforce(decision)


def _answer[T](result: T | Refusal | None) -> T:
    if result is None:
        raise _not_found()
    if isinstance(result, Refusal):
        _raise(result)
    return result


@router.post(
    "/messages",
    response_model=IngestResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ingest_rate_limit), Depends(_ingest_token)],
    responses={
        401: {"description": "Wrong or missing token"},
        404: {"description": "Ingestion is off, or the address is no clinic's inbox"},
    },
)
def ingest_message(message_in: InboundMessageIn, response: Response) -> IngestResult:
    """The mailbox adapter delivers one received email. Not a user route.

    The tenant is the one the `to` address names. A redelivery answers `200` with the original
    message id and changes nothing (R18).
    """
    try:
        outcome = pipeline.ingest(
            pipeline.InboundMessage(
                provider_message_id=message_in.provider_message_id,
                from_address=str(message_in.from_address),
                to_address=str(message_in.to_address),
                subject=message_in.subject,
                received_at=message_in.received_at,
                spf_result=message_in.spf_result,
                dkim_result=message_in.dkim_result,
                dmarc_result=message_in.dmarc_result,
                attachments=[
                    pipeline.InboundAttachment(
                        filename=item.filename,
                        content_type=item.content_type,
                        data=item.content_base64,
                    )
                    for item in message_in.attachments
                ],
            )
        )
    except pipeline.UnknownMailbox as error:
        raise _not_found() from error
    if outcome.duplicate:
        response.status_code = status.HTTP_200_OK
    return IngestResult(
        message_id=outcome.message_id,
        processing_state=outcome.processing_state,
        duplicate=outcome.duplicate,
    )


class InboxAddress(BaseModel):
    address: str


@router.get("/address", response_model=InboxAddress)
def inbox_address(*, actor: ActorDep) -> InboxAddress:
    """The address this clinic gives the TGA for approval letters."""
    _authorize(actor, action=service.READ)
    return InboxAddress(address=pipeline.inbox_address(actor.tenant_id))


@router.get(
    "/messages", response_model=InboxQueue, dependencies=[Depends(read_rate_limit)]
)
def list_messages(
    *,
    actor: ActorDep,
    state: Annotated[str | None, Query(pattern="^[A-Z]{1,16}$")] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_QUEUE)] = 50,
) -> InboxQueue:
    """The review queue, oldest first; the open states unless `state` names one."""
    _authorize(actor, action=service.READ)
    if state is not None and state not in MESSAGE_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_STATE", "message": "Unknown state"},
        )
    return service.list_queue(actor=actor, state=state, limit=limit)


@router.get(
    "/messages/{message_id}",
    response_model=InboxMessageDetail,
    dependencies=[Depends(read_rate_limit)],
)
def read_message(*, actor: ActorDep, message_id: uuid.UUID) -> InboxMessageDetail:
    _authorize(actor, action=service.READ)
    return _answer(service.read_message(actor=actor, message_id=message_id))


@router.get(
    "/attachments/{attachment_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    dependencies=[Depends(read_rate_limit)],
)
def attachment_content(*, actor: ActorDep, attachment_id: uuid.UUID) -> Response:
    """The original PDF, only if it was scanned clean and its hash still verifies (R5, R6)."""
    _authorize(actor, action=service.READ)
    try:
        result = service.attachment_content(actor=actor, attachment_id=attachment_id)
    except service.IntegrityFailure as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INTEGRITY_CHECK_FAILED",
                "message": "The stored file failed its integrity check",
            },
        ) from error
    if result is None:
        raise _not_found()
    _filename, data = result
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            # Shown inline in the review screen, never sniffed as anything else, never cached.
            "Content-Disposition": 'inline; filename="approval.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/messages/{message_id}/claim", response_model=InboxMessageDetail)
def claim_message(*, actor: ActorDep, message_id: uuid.UUID) -> InboxMessageDetail:
    _authorize(actor, action=service.DECIDE)
    return _answer(service.claim(actor=actor, message_id=message_id))


@router.post("/messages/{message_id}/accept", response_model=DecisionResult)
def accept_message(
    *, actor: ActorDep, message_id: uuid.UUID, request: AcceptRequest
) -> DecisionResult:
    """Accept or correct the values; creates a `PENDING` approval a second clinician verifies."""
    _authorize(actor, action=service.DECIDE)
    return _answer(service.accept(actor=actor, message_id=message_id, request=request))


@router.post("/messages/{message_id}/reject", response_model=DecisionResult)
def reject_message(
    *, actor: ActorDep, message_id: uuid.UUID, request: RejectRequest
) -> DecisionResult:
    _authorize(actor, action=service.DECIDE)
    return _answer(
        service.reject(
            actor=actor, message_id=message_id, reason_code=request.reason_code
        )
    )


@router.post("/messages/{message_id}/defer", response_model=DecisionResult)
def defer_message(*, actor: ActorDep, message_id: uuid.UUID) -> DecisionResult:
    _authorize(actor, action=service.DECIDE)
    return _answer(service.defer(actor=actor, message_id=message_id))
