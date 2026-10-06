from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging

FRONTEND_DIR = Path(__file__).parent / "frontend"

# Installed here, on the application's own import path, so the redaction filter and the JSON sink
# are part of every process that serves a request — never only of the test harness
# (`16-operations-and-observability/06-test-plan.md` S1).
configure_logging()


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

install_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last, so it is the outermost user middleware: every request gets its handle before any
# other middleware runs, and the echo header is present on a CORS refusal as well as a success.
app.add_middleware(CorrelationIdMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)

if FRONTEND_DIR.exists():
    app.frontend("/", directory=FRONTEND_DIR)
