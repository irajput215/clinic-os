from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

import sentry_sdk
from anyio import to_thread
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.telemetry import TelemetryConfig
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.db import warm_pool
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.server_timing import ServerTimingMiddleware
from app.core.static_cache import StaticCacheMiddleware

FRONTEND_DIR = Path(__file__).parent / "frontend"

# Installed here, on the application's own import path, so the redaction filter and the JSON sink
# are part of every process that serves a request — never only of the test harness
# (`16-operations-and-observability/06-test-plan.md` S1).
configure_logging()


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Open pooled connections (and wake a suspended Neon compute) before the first request needs
    # them, off the event loop; never fails start-up (`app.core.db.warm_pool`).
    await to_thread.run_sync(warm_pool)
    yield


# FastAPI's native OpenTelemetry (fastapi[standard] >= 0.143) is off, explicitly. Its spans carry the
# request path and query string, and with `FASTAPI_OTEL_AUTO_CONFIGURE=true` plus an OTLP endpoint in
# the environment (which a hosting platform can set) they would leave the process: a new data flow
# for identifiers, which INV-5 and the build contract put behind a decision. Deny by default; the
# open decision is recorded in docs/reference/open-questions.md.
NATIVE_TELEMETRY_OFF: Final[TelemetryConfig] = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "auto_configure": False,
}

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    telemetry=NATIVE_TELEMETRY_OFF,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

install_exception_handlers(app)

# Innermost: caching and precompressed variants for the built app (`app/core/static_cache.py`).
app.add_middleware(StaticCacheMiddleware, directory=FRONTEND_DIR, api_prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every response - API, /docs and the app's HTML at `/` - refuses framing and sniffing
# (`app/core/security_headers.py`). Outside CORS, so a CORS refusal carries the headers as well.
app.add_middleware(SecurityHeadersMiddleware)

# Added last, so it is the outermost user middleware: every request gets its handle before any
# other middleware runs, and the echo header is present on a CORS refusal as well as a success.
app.add_middleware(CorrelationIdMiddleware)

# Outermost of all: it opens the request's database measurement before anything else runs, so the
# request line written by the correlation middleware can carry it (`app/core/server_timing.py`).
app.add_middleware(ServerTimingMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)

if FRONTEND_DIR.exists():
    app.frontend("/", directory=FRONTEND_DIR)
