"""The edge middleware: correlation handles, the request log line and the echo header.

Feature `16-operations-and-observability` requires that a request has a correlation handle
*before* anything else touches it:

- `request_id` is generated at the edge if the caller did not supply one, validated if it did,
  and propagated through every call (`03-design.md` "Structured log contract").
- `correlation_id` joins a log line to an audit event across a queue or a provider. For a
  synchronous HTTP request it is the same handle as `request_id` unless the caller supplied one.
- The handle is echoed on the response as `X-Request-ID`, so a clinician can quote it and an
  operator can find the line (`06-test-plan.md` R1).
- The handle reaches `app.core.db.tenant_transaction` through the contextvar set here, so every
  database session in the request carries `app.request_id` (`03-design.md` §"Deny-by-default
  request path" step 1).

**Validation is a bound, not a courtesy.** An inbound handle is accepted only when it is short
and drawn from a safe alphabet. A value with a space, a newline or anything outside
``[A-Za-z0-9._:-]`` is refused rather than sanitised, because a header that can forge a log line
is a log-injection vector (`04-threat-model.md` T-16.10) and a value that is a health identifier
is PHI planted in our sink by a caller (`INV-5`). A refused value is replaced by a generated one;
it is never logged, never echoed and never trusted.
"""

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_context
from app.core.server_timing import request_log_fields

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

MAX_HANDLE_LENGTH = 128
_HANDLE_CHARSET = re.compile(rf"^[A-Za-z0-9._:-]{{1,{MAX_HANDLE_LENGTH}}}$")

# A health identifier is a plausible-looking handle by shape alone: ten digits is a Medicare
# number and sixteen is an IHI (`05-data-and-audit.md`). Refusing them here means a caller cannot
# make the correlation path a route for health information into the log sink.
_HEALTH_IDENTIFIER_SHAPED = re.compile(r"^(?:\d{10}|\d{16})$")

#: The route is the *template* (`/api/v1/patients/{patient_id}`), never the resolved path and
#: never a path parameter (`01-requirements.md` R1). A request that matched no route gets this
#: constant instead of its own path, because the path of an unmatched request is attacker input.
UNMATCHED_ROUTE = "<unmatched>"


def acceptable_handle(candidate: str | None) -> str | None:
    """Return the candidate if it is a safe correlation handle, otherwise ``None``."""
    if candidate is None:
        return None
    if not _HANDLE_CHARSET.match(candidate):
        return None
    if _HEALTH_IDENTIFIER_SHAPED.match(candidate):
        return None
    return candidate


def request_id_from_scope(scope: Scope) -> str | None:
    """Read the handle this middleware put on the ASGI scope.

    An exception handler installed on Starlette's `ServerErrorMiddleware` runs outside every
    user middleware, after the contextvar has been reset, so it reads the handle from the scope.
    """
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    request_id = state.get("request_id")
    return request_id if isinstance(request_id, str) else None


def _outcome(status: int) -> str:
    """The closed outcome vocabulary from `03-design.md`: one of four values, never free text."""
    if status < 400:
        return "success"
    if status in {401, 403}:
        return "denied"
    if status == 429:
        return "rate_limited"
    return "error"


def route_template(scope: Scope) -> str:
    """The matched route's *template*, or a constant when nothing matched.

    FastAPI's `APIRoute.matches` returns the matched route in its child scope and Starlette's
    router merges that child scope into the request scope, so `scope["route"]` is set by the time
    the call returns. Its `.path` is the template — `{patient_id}`, never the resolved value. In
    this FastAPI version an included router is mounted as one route, so the template is
    router-relative (`/patients/{patient_id}`) and the `/api/v1` prefix lives on the mount; the
    template is still stable and still free of any caller-supplied value, which is what the
    contract requires.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class CorrelationIdMiddleware:
    """Pure-ASGI middleware: assign, propagate and echo the correlation handles.

    Pure ASGI rather than `BaseHTTPMiddleware` so the `send` wrapper can add the echo header to
    the real response without buffering it, and so the contextvar is bound for the whole call.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = acceptable_handle(headers.get(REQUEST_ID_HEADER)) or uuid4().hex
        correlation_id = (
            acceptable_handle(headers.get(CORRELATION_ID_HEADER)) or request_id
        )

        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["correlation_id"] = correlation_id

        started = perf_counter()
        status = 500

        async def send_with_handle(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with request_context(request_id, correlation_id):
            try:
                await self.app(scope, receive, send_with_handle)
            finally:
                latency_ms = round((perf_counter() - started) * 1000, 3)
                # Always emitted, including on the error path: a request that produced no line
                # is a request nothing can be reconstructed from.
                _log_request_line(
                    scope=scope,
                    method=str(scope.get("method", "")).upper(),
                    status=status,
                    latency_ms=latency_ms,
                )


def _log_request_line(
    *,
    scope: Scope,
    method: str,
    status: int,
    latency_ms: float,
) -> None:
    """Emit the one request line: typed fields only, one JSON object, no free text."""
    logger.info(
        "http.request",
        extra={
            "log_category": "application",
            "route": route_template(scope),
            "method": method,
            "status": status,
            "latency_ms": latency_ms,
            "outcome": _outcome(status),
            "error_class": _error_class(status),
            # Durations, counts and the serving instance: never SQL, parameters or identifiers.
            **request_log_fields(),
        },
    )


def _error_class(status: int) -> str | None:
    """A classified error type, never a message, an SQL fragment or provider text."""
    if status < 400:
        return None
    return f"http_{status}"
