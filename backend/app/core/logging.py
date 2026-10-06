"""Structured JSON logging, the PHI redaction filter and the log envelope validator.

Requirement `INV-5` (`docs/reference/build-contract.md` §5) and feature
`16-operations-and-observability`:

- **One JSON object per line**, built from the field set in
  [`05-data-and-audit.md`](../../../../docs/features/16-operations-and-observability/05-data-and-audit.md)
  and the log contract in `03-design.md`. `json.dumps` is the only serialiser: no third-party
  logging dependency is added, because the contract's whole point is that the logger is small
  enough to audit.
- **Redaction runs before the sink write and has no bypass.** Every record that reaches the
  handler passes through :class:`RedactionFilter` — debug, trace, crash and error paths included
  (`03-design.md` "Hard rule"; `06-test-plan.md` R3). The filter redacts by *field key* (a
  declared sensitive field is replaced whatever its value) and by *value pattern* (health
  identifiers, born dates, tokens and credential assignments are scrubbed from free text).
- **A line without `request_id` and `correlation_id` is dropped and counted, never emitted**
  (`03-design.md` "Structured log contract"; `06-test-plan.md` F1). The counter is exposed as
  :func:`envelope_drop_count` so the drop is observable rather than silent.

Two honest limits are recorded here rather than hidden:

- Redaction by pattern cannot recognise a patient *name* embedded in free text, because a name
  has no shape. Names are caught when they arrive as a typed field (`given_name`, `patient_name`,
  …), which is why the contract requires typed fields and forbids free-text concatenation; a
  call site that interpolates a name into the message defeats the filter. The typed-field rule is
  the control, and the message templates in `app/core/correlation.py` and `app/core/errors.py`
  are constant strings.
- The key deny-list is deliberately broad and fails closed: a field whose *name* merely looks
  sensitive is redacted even when its value is harmless. A redacted line is a safe line.

The handler is installed by :func:`configure_logging`, called from `app.main` at import time, so
the application — not the test suite — owns the sink (`06-test-plan.md` S1).
"""

import hmac
import json
import logging
import os
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from hashlib import sha256
from importlib import metadata
from threading import Lock
from typing import Any, Final
from uuid import UUID

from app.core.config import settings

# --- The JSON sink -----------------------------------------------------------------------------

HANDLER_NAME: Final = "clinos.json"
REDACTED: Final = "[REDACTED]"

#: The five stores in `03-design.md` §"Structured log contract". One stream may only claim one.
LOG_CATEGORIES: Final = frozenset(
    {"application", "security", "audit", "integration", "infrastructure"}
)

#: The mandatory request-line field set (`01-requirements.md` R1).
MANDATORY_REQUEST_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "correlation_id",
    "tenant_context",
    "user_context",
    "service",
    "route",
    "method",
    "status",
    "latency_ms",
    "outcome",
    "log_category",
    "app_version",
    "environment",
)

#: Attributes `logging` puts on every record. They are never copied into the line verbatim, so a
#: record's own extras are the only source of additional fields.
_RESERVED_RECORD_ATTRIBUTES: Final = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# --- Request scope -----------------------------------------------------------------------------

#: Correlation handles only: INTERNAL, safe in a log line (`05-data-and-audit.md`).
request_id_var: ContextVar[str | None] = ContextVar("clinos_request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar(
    "clinos_correlation_id", default=None
)

#: Per-request, already-pseudonymised tenant and actor context. A mutable dict held in a
#: contextvar: the middleware creates it at the edge, `tenant_transaction` fills it in once a
#: transaction has resolved an identity, and the request line reads it at the end. The raw
#: identifier is never stored here — see :func:`pseudonymise`.
_request_log_context: ContextVar[dict[str, str | None] | None] = ContextVar(
    "clinos_request_log_context", default=None
)


def current_request_id() -> str | None:
    """The correlation handle of the request being served, if there is one."""
    return request_id_var.get()


def current_correlation_id() -> str | None:
    """The per-intent handle that joins a log line to an audit event, if there is one."""
    return correlation_id_var.get()


def current_tenant_context() -> str | None:
    """The keyed pseudonym of the request's tenant, or ``None`` outside a transaction."""
    return (_request_log_context.get() or {}).get("tenant_context")


def current_user_context() -> str | None:
    """The keyed pseudonym of the request's actor, or ``None`` outside a transaction."""
    return (_request_log_context.get() or {}).get("user_context")


@contextmanager
def request_context(
    request_id: str, correlation_id: str | None = None
) -> Iterator[None]:
    """Bind the correlation handles for the duration of the block.

    Used by the edge middleware, and again by an error handler that runs *after* the middleware
    has unwound — a handler installed on Starlette's `ServerErrorMiddleware` is outside every
    user middleware, so it re-binds the context from `request.state` before it logs.
    """
    request_token: Token[str | None] = request_id_var.set(request_id)
    correlation_token: Token[str | None] = correlation_id_var.set(
        correlation_id or request_id
    )
    context_token: Token[dict[str, str | None] | None] = _request_log_context.set({})
    try:
        yield
    finally:
        _request_log_context.reset(context_token)
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)


def record_identity(
    *, tenant_id: UUID | str | None, actor_id: UUID | str | None
) -> None:
    """Record keyed pseudonyms for the request line. Raw identifiers never enter a log field.

    Called by `app.core.db.tenant_transaction`, which is the only place that has resolved a
    tenant, and only when a request context is open.
    """
    context = _request_log_context.get()
    if context is None:
        return
    if tenant_id is not None:
        context["tenant_context"] = pseudonymise(tenant_id, prefix="t")
    if actor_id is not None:
        context["user_context"] = pseudonymise(actor_id, prefix="u")


def pseudonymise(value: UUID | str, *, prefix: str) -> str:
    """Return a keyed pseudonym: stable inside an environment, useless outside it.

    `05-data-and-audit.md` requires application logs to carry a *keyed pseudonym* of the tenant
    and the actor, never the raw identifier. HMAC-SHA256 under the application secret gives
    exactly that: the same tenant maps to the same handle in every line (so lines join), and the
    handle cannot be reversed without the secret.
    """
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), str(value).encode("utf-8"), sha256
    ).hexdigest()
    return f"{prefix}_{digest[:16]}"


# --- Redaction ---------------------------------------------------------------------------------

#: A field whose *name* contains any of these tokens is redacted whatever it holds. Tokens are
#: matched against the `_`/`-`/`.`-separated parts of a key, so `patient_email` is caught and
#: `email_template` is caught too — over-redaction is the safe direction.
_SENSITIVE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        # SECRET: disclosure grants access or defeats a control.
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "secret",
        "secrets",
        "token",
        "tokens",
        "apikey",
        "api_key",
        "authorization",
        "auth",
        "bearer",
        "cookie",
        "cookies",
        "session",
        "credential",
        "credentials",
        "private",
        "mfa",
        "otp",
        "seed",
        "signature",
        # HEALTH_INFORMATION: direct identifiers and health identifiers.
        "name",
        "names",
        "surname",
        "given",
        "family",
        "dob",
        "birth",
        "birthdate",
        "medicare",
        "ihi",
        "health",
        "identifier",
        "address",
        "phone",
        "mobile",
        "email",
        "contact",
        "patient",
        "subject",
        # HIGHLY_SENSITIVE: bodies and clinical payloads are prohibited from every sink.
        "body",
        "payload",
        "json",
        "content",
        "data",
        "note",
        "notes",
        "document",
        "ocr",
        "prescription",
        "tga",
        "approval",
        "clinical",
        "diagnosis",
        "medication",
        "medicine",
        "result",
        "results",
    }
)

_KEY_SPLIT: Final = re.compile(r"[^A-Za-z0-9]+")

#: Value patterns. Applied to every string that is about to be emitted, so a health identifier
#: or a credential is scrubbed even when it arrives in a free-text field.
#:
#: Deliberately absent: a UUID pattern. A UUID is a resource reference, and the correlation
#: handles themselves are UUIDs — redacting every UUID would break the join the contract exists
#: to provide.
_VALUE_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # A JWT anywhere in a string.
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        REDACTED,
    ),
    # An `Authorization:`/`Cookie:`-style header, however it was flattened into the message.
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key)"
            r"\s*:\s*[^\r\n]+"
        ),
        rf"\1: {REDACTED}",
    ),
    # A credential assignment: `password=…`, `token: …`, `api_key=…`.
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|passphrase|secret|token|api[_-]?key)"
            r"\s*[:=]\s*\S+"
        ),
        rf"\1={REDACTED}",
    ),
    # An authentication scheme with an opaque value: `Bearer …`, `Basic …`.
    (
        re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"),
        rf"\1 {REDACTED}",
    ),
    # A Medicare number: ten digits, optionally grouped 4-5-1.
    (re.compile(r"(?<!\d)\d{4}\s\d{5}\s\d(?!\d)"), REDACTED),
    (re.compile(r"(?<!\d)\d{10}(?!\d)"), REDACTED),
    # An IHI: sixteen digits.
    (re.compile(r"(?<!\d)\d{16}(?!\d)"), REDACTED),
    # A date of birth, ISO or Australian day-first.
    (
        re.compile(
            r"(?<!\d)(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)"
        ),
        REDACTED,
    ),
    (
        re.compile(
            r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}(?!\d)"
        ),
        REDACTED,
    ),
)


def _key_is_sensitive(key: str) -> bool:
    tokens = {token.lower() for token in _KEY_SPLIT.split(key) if token}
    return bool(tokens & _SENSITIVE_KEY_TOKENS)


def scrub_text(value: str) -> str:
    """Scrub every known value pattern out of one string."""
    scrubbed = value
    for pattern, replacement in _VALUE_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def _scrub_jsonable(value: Any) -> Any:  # noqa: ANN401 - arbitrary log field values
    """Return a JSON-serialisable copy of a log field with every value scrubbed."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _key_is_sensitive(str(key)) else _scrub_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub_jsonable(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return scrub_text(str(value))


class RedactionFilter(logging.Filter):
    """Redact a record in place before any handler formats it.

    There is no bypass and no level exemption: this filter is attached to the sink handler, so a
    debug line, a crash line and an error line all pass through it (`03-design.md` "Hard rule").
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)
        elif record.msg is not None:
            record.msg = _scrub_jsonable(record.msg)

        if isinstance(record.args, Mapping):
            record.args = {
                key: REDACTED if _key_is_sensitive(str(key)) else _scrub_jsonable(value)
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub_jsonable(value) for value in record.args)

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_ATTRIBUTES:
                continue
            record.__dict__[key] = (
                REDACTED if _key_is_sensitive(key) else _scrub_jsonable(value)
            )

        return True


class EnvelopeFilter(logging.Filter):
    """Drop a line that cannot be correlated, and count it.

    A line without `request_id` and `correlation_id` fails the envelope validator closed: it is
    dropped and counted rather than emitted, so the sink can never contain an unattributable
    line (`06-test-plan.md` F1).

    The count is per *line*, not per handler: the same record reaches every handler, so the first
    one to drop it marks it and the rest do not double-count. Without that, a second configured
    sink would inflate the only signal an operator has for "how many lines were unattributable".
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = record.__dict__.get("request_id") or current_request_id()
        correlation_id = record.__dict__.get("correlation_id") or (
            current_correlation_id()
        )
        if not request_id or not correlation_id:
            if not record.__dict__.get(_DROP_MARKER):
                record.__dict__[_DROP_MARKER] = True
                _count_envelope_drop()
            return False
        return True


#: Set on a record the envelope validator has already dropped, so N handlers count one line once.
#: The leading underscore keeps it out of the JSON line (see `JSONFormatter.format`).
_DROP_MARKER: Final = "_clinos_envelope_dropped"


_envelope_drops = 0
_envelope_drops_lock = Lock()


def _count_envelope_drop() -> None:
    global _envelope_drops
    with _envelope_drops_lock:
        _envelope_drops += 1


def envelope_drop_count() -> int:
    """How many lines the envelope validator has dropped since the process started."""
    with _envelope_drops_lock:
        return _envelope_drops


# --- Formatting --------------------------------------------------------------------------------


def _app_version() -> str:
    try:
        return metadata.version("app")
    except (
        metadata.PackageNotFoundError
    ):  # pragma: no cover - installed in every real run
        return "unknown"


def _environment() -> str:
    # One of Development, Staging or Production (`03-design.md`). This repository has one
    # non-production environment name and no staging name; anything that is not development is
    # reported as production, which is the conservative reading and never flatters the setting.
    return "development" if settings.FASTAPI_ENV == "development" else "production"


_SERVICE: Final = settings.PROJECT_NAME
_APP_VERSION: Final = _app_version()
_ENVIRONMENT: Final = _environment()


def _request_line_context() -> dict[str, str | None]:
    return _request_log_context.get() or {}


class JSONFormatter(logging.Formatter):
    """One JSON object per line, with the contract's field set and the record's own extras."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - logging's API
        context = _request_line_context()
        fields: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": _SERVICE,
            "environment": _ENVIRONMENT,
            "app_version": _APP_VERSION,
            "log_category": record.__dict__.get("log_category", "application"),
            "request_id": record.__dict__.get("request_id") or current_request_id(),
            "correlation_id": record.__dict__.get("correlation_id")
            or current_correlation_id(),
            "tenant_context": record.__dict__.get("tenant_context")
            if "tenant_context" in record.__dict__
            else context.get("tenant_context"),
            "user_context": record.__dict__.get("user_context")
            if "user_context" in record.__dict__
            else context.get("user_context"),
            "route": record.__dict__.get("route"),
            "method": record.__dict__.get("method"),
            "status": record.__dict__.get("status"),
            "latency_ms": record.__dict__.get("latency_ms"),
            "outcome": record.__dict__.get("outcome"),
            "error_class": record.__dict__.get("error_class"),
        }

        for key, value in record.__dict__.items():
            # A leading underscore is `logging`'s own bookkeeping (and the envelope filter's drop
            # marker): internal state, never a field of the line.
            if (
                key.startswith("_")
                or key in _RESERVED_RECORD_ATTRIBUTES
                or key in fields
            ):
                continue
            fields[key] = value

        if record.exc_info:
            # The traceback is diagnostic and stays in the log; the *client* envelope never
            # carries it. It is scrubbed like every other value, because a driver error message
            # can quote the statement and its parameters.
            fields["exception"] = scrub_text(self.formatException(record.exc_info))
        if record.stack_info:
            fields["stack_info"] = scrub_text(record.stack_info)

        try:
            return json.dumps(fields, default=str, ensure_ascii=True, sort_keys=True)
        except TypeError, ValueError:  # pragma: no cover - defensive
            return json.dumps(
                {
                    "timestamp": fields["timestamp"],
                    "level": "ERROR",
                    "logger": record.name,
                    "message": REDACTED,
                    "request_id": fields["request_id"],
                    "correlation_id": fields["correlation_id"],
                    "log_category": "application",
                    "error_class": "log_serialisation_failed",
                },
                sort_keys=True,
            )


def build_handler(stream: Any = None) -> logging.Handler:  # noqa: ANN401 - a writable stream
    """Build one JSON sink handler with redaction and the envelope validator attached.

    Exposed so a test can assert the exact pipeline the application installs, rather than
    approximating it.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.name = HANDLER_NAME
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RedactionFilter())
    handler.addFilter(EnvelopeFilter())
    return handler


def configure_logging(*, level: str | int | None = None) -> logging.Handler:
    """Install the application's JSON sink on the root logger. Idempotent.

    Called from `app.main` at import time, so the filter is installed by the application's own
    import path and not only by a test harness.
    """
    configured: str | int = (
        level if level is not None else os.environ.get("LOG_LEVEL", "INFO")
    )
    root = logging.getLogger()
    for handler in root.handlers:
        if handler.name == HANDLER_NAME:
            return handler

    handler = build_handler()
    handler.setLevel(configured)
    root.addHandler(handler)
    # The root logger's *level* gates records before they reach a handler, so the default
    # WARNING would silently drop every INFO request line.
    root.setLevel(configured)
    return handler
