"""The one error envelope: `application/problem+json`, and nothing that helps an attacker.

`docs/reference/build-contract.md` control 9 — *"One error envelope, no diagnostics to the client,
`request_id` correlation, fail closed"* — and feature `16-operations-and-observability`.

Three handlers are installed, and every error a client can observe passes through exactly one of
them:

======================  ==============================  ====================================
Exception               Status                          Body
======================  ==============================  ====================================
`HTTPException`         the exception's own status      the exception's own `detail`, unchanged
`RequestValidationError`422                             the validation errors, minus the values
anything else           500                             `Internal server error`, nothing more
======================  ==============================  ====================================

**The body is RFC 7807** (`application/problem+json`): `type`, `title`, `status`, `detail`,
`instance`. Two deliberate departures from the RFC are recorded rather than hidden:

1. `detail` is **not** always a string. The API's existing contract — which the whole test suite
   and the generated TypeScript client depend on — is that a refusal may carry a machine-readable
   object (`{"code": "PERMISSION_NOT_HELD", …}`). This envelope preserves that payload byte for
   byte and adds the RFC fields *around* it, so the change is additive for every existing caller.
   `title` carries the human-readable sentence the RFC expects `detail` to hold.
2. `request_id` is added as a top-level extension member. Control 9 requires the correlation handle
   to be present in the response as well as in the log; the RFC has no field for it and `instance`
   is a different thing (the request path).

**No diagnostics leave the process.** A `500` body is a constant. The traceback, the SQL statement,
its bound parameters, a table or column name and an internal path go to the log sink — where the
redaction filter scrubs them — and never to the client. Validation errors are narrowed to
`type`/`loc`/`msg`: FastAPI's default also echoes the offending `input` value, and for a body-level
failure that value is the **whole request body**, which is exactly the HIGHLY_SENSITIVE payload
`INV-5` prohibits from an error response.

`instance` is the request **path only** — never the query string, which the contract forbids
carrying identifiers in the first place.
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import request_id_from_scope, route_template
from app.core.logging import current_correlation_id, current_request_id, request_context

logger = logging.getLogger("app.errors")

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"

#: RFC 7807 §4.2: the type used when the problem has no more specific type. The API's stable,
#: machine-readable code lives in `detail.code`, where Control 9's contract already put it.
ABOUT_BLANK = "about:blank"

#: The only validation-error members that may reach the client. `input` and `ctx` are dropped:
#: both can carry the submitted value, and on a body-level failure `input` is the whole body.
_SAFE_VALIDATION_MEMBERS = ("type", "loc", "msg")

GENERIC_INTERNAL_DETAIL = "Internal server error"

#: `error_class` is a classified type — never a message, an SQL fragment or provider text.
_ERROR_CLASSES: tuple[tuple[type[BaseException], str], ...] = (
    (OperationalError, "database_unavailable"),
    (IntegrityError, "database_constraint"),
    (DBAPIError, "database_error"),
    (TimeoutError, "timeout"),
)


def classify_error(exc: BaseException) -> str:
    """Map an exception to a coarse, stable `error_class` value."""
    for exception_type, name in _ERROR_CLASSES:
        if isinstance(exc, exception_type):
            return name
    return type(exc).__name__


def request_id_for(request: Request) -> str | None:
    """The request's correlation handle, from the scope or the context, whichever survives."""
    return request_id_from_scope(request.scope) or current_request_id()


def request_instance(request: Request) -> str:
    """The RFC 7807 `instance`: the resolution path, with path-parameter *values* removed.

    A cross-tenant `404` must not echo the resource id it refused — that is the assertion in
    `tests/patients/test_denials.py::test_cross_tenant_read_is_404_with_no_patient_data`, and it is
    the same rule that keeps path parameters out of the log line. So the resolved segment is
    replaced by its name: `/api/v1/patients/{patient_id}`. The path is never taken from the query
    string, which the contract forbids carrying identifiers in at all.

    A request that matched no route has no parameters to remove; its `instance` is the path the
    caller asked for, which is the caller's own input and the only identifier available. The
    `request_id` member is what identifies the individual occurrence.
    """
    path = request.url.path
    path_params = request.scope.get("path_params") or {}
    for name, value in path_params.items():
        if value is not None:
            path = path.replace(f"/{value}", f"/{{{name}}}")
    return path


def problem_body(
    request: Request,
    *,
    status_code: int,
    detail: Any,
    title: str | None = None,
) -> dict[str, Any]:
    """Build the RFC 7807 body, preserving `detail` exactly."""
    return {
        "type": ABOUT_BLANK,
        "title": title or _status_phrase(status_code),
        "status": status_code,
        "detail": detail,
        "instance": request_instance(request),
        "request_id": request_id_for(request),
    }


def problem_response(
    request: Request,
    *,
    status_code: int,
    detail: Any,
    headers: dict[str, str] | None = None,
    title: str | None = None,
) -> JSONResponse:
    """One JSON response, one media type, the correlation handle echoed."""
    response_headers = dict(headers or {})
    request_id = request_id_for(request)
    if request_id is not None:
        response_headers.setdefault(REQUEST_ID_HEADER, request_id)
    return JSONResponse(
        status_code=status_code,
        content=problem_body(
            request, status_code=status_code, detail=detail, title=title
        ),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=response_headers,
    )


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:  # pragma: no cover - a non-standard status from a handler
        return "Error"


def _safe_validation_errors(
    errors: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only the members that cannot echo a submitted value back to the caller."""
    return [
        {
            member: error[member]
            for member in _SAFE_VALIDATION_MEMBERS
            if member in error
        }
        for error in errors
    ]


@contextmanager
def _error_log_context(request: Request) -> Iterator[None]:
    """Re-bind the correlation handles around a log emitted outside the middleware.

    Starlette installs the handler for `Exception` on `ServerErrorMiddleware`, which is *outside*
    every user middleware: by the time it runs, the edge contextvar has been reset. Rebinding
    from the scope keeps the diagnostic line attributable instead of dropping it as
    uncorrelated.
    """
    request_id = request_id_for(request)
    if request_id is None:
        yield
        return
    with request_context(request_id, current_correlation_id()):
        yield


def _generic_internal_response(request: Request) -> JSONResponse:
    """The one body an unexpected failure may produce."""
    return problem_response(request, status_code=500, detail=GENERIC_INTERNAL_DETAIL)


def _as_http_exception(exc: Exception) -> StarletteHTTPException | None:
    """Narrow to the refusal type, or ``None``.

    A handler registered through `add_exception_handler` receives whatever Starlette matched, so
    the parameter has to be `Exception`. FastAPI dispatches by exception type, so this narrow
    always succeeds in practice; if a future registration ever sent something else, the caller
    fails closed to the generic envelope rather than raising inside an error handler.
    """
    return exc if isinstance(exc, StarletteHTTPException) else None


def _as_validation_error(exc: Exception) -> RequestValidationError | None:
    """Narrow to the validation type, or ``None``. See :func:`_as_http_exception`."""
    return exc if isinstance(exc, RequestValidationError) else None


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Every deliberate refusal: `detail` and headers preserved, the envelope added."""
    http_exc = _as_http_exception(exc)
    if http_exc is None:  # pragma: no cover - FastAPI dispatches by exception type
        return _generic_internal_response(request)
    return problem_response(
        request,
        status_code=http_exc.status_code,
        detail=http_exc.detail,
        headers=dict(http_exc.headers) if http_exc.headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """A `422` that says which field failed without repeating what was sent."""
    validation_error = _as_validation_error(exc)
    if (
        validation_error is None
    ):  # pragma: no cover - FastAPI dispatches by exception type
        return _generic_internal_response(request)
    return problem_response(
        request,
        status_code=422,
        detail=jsonable_encoder(_safe_validation_errors(validation_error.errors())),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fail closed: the client gets a constant, the operator gets the diagnostic."""
    with _error_log_context(request):
        # The traceback is scrubbed by the logging pipeline before it is written. This is the one
        # place a diagnostic is allowed to exist, and it is server-side only.
        logger.exception(
            "http.unhandled_exception",
            extra={
                "log_category": "application",
                "error_class": classify_error(exc),
                "route": route_template(request.scope),
                "method": request.method,
            },
        )
    return problem_response(request, status_code=500, detail=GENERIC_INTERNAL_DETAIL)


def install_exception_handlers(app: FastAPI) -> None:
    """Install the three handlers. Additive: each replaces FastAPI's default of the same key."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
