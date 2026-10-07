"""Every response carries the browser security headers the host must send.

`docs2/architecture.md` "Security measures in the app" (clickjacking) and
`docs/tasks/01-phase-1-foundations.md` T1-42: `frame-ancestors` is ignored in a `<meta>` policy, so
framing protection exists only if the server sends it, on the SPA's HTML as much as on the API.
"""

from collections.abc import Mapping

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware
from app.main import app

EXPECTED = {
    "content-security-policy": "frame-ancestors 'none'",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=31536000",
}


def _assert_headers(headers: Mapping[str, str]) -> None:
    for name, value in EXPECTED.items():
        assert headers[name] == value, name


def test_the_declared_set_is_the_tested_set() -> None:
    assert {k.lower(): v for k, v in SECURITY_HEADERS.items()} == EXPECTED


@pytest.mark.parametrize(
    "path",
    [
        f"{settings.API_V1_STR}/utils/health-check/",
        f"{settings.API_V1_STR}/openapi.json",
        "/docs",
        "/redoc",
    ],
)
def test_api_and_docs_responses_carry_the_headers(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    _assert_headers(response.headers)


def test_a_refusal_carries_the_headers_too(client: TestClient) -> None:
    unauthenticated = client.get(f"{settings.API_V1_STR}/users/me")
    unmatched = client.get(f"{settings.API_V1_STR}/no-such-route")

    assert unauthenticated.status_code == 401
    assert unmatched.status_code == 404
    _assert_headers(unauthenticated.headers)
    _assert_headers(unmatched.headers)


def test_swagger_ui_still_renders(client: TestClient) -> None:
    """The headers forbid framing only; they add no script or style policy that breaks /docs."""
    response = client.get("/docs")

    assert "SwaggerUIBundle" in response.text
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_an_html_page_is_not_frameable() -> None:
    """The SPA mount serves HTML through the same middleware stack.

    A route that sends its own policy keeps it, and framing is still refused: a second
    `Content-Security-Policy` header is enforced alongside the first, never instead of it.
    """
    page = FastAPI()

    @page.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<!doctype html><title>x</title>"

    @page.get("/own-policy")
    def own_policy() -> HTMLResponse:
        return HTMLResponse(
            "<p>x</p>", headers={"Content-Security-Policy": "default-src 'self'"}
        )

    page.add_middleware(SecurityHeadersMiddleware)
    with TestClient(page) as local:
        response = local.get("/")
        overridden = local.get("/own-policy")

    _assert_headers(response.headers)
    assert overridden.headers.get_list("content-security-policy") == [
        "default-src 'self'",
        "frame-ancestors 'none'",
    ]
    assert overridden.headers["x-frame-options"] == "DENY"


def test_an_unhandled_error_carries_the_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last-resort `500` is answered outside every user middleware, so it sets them itself."""

    def boom() -> bool:
        raise RuntimeError("readiness probe exploded")

    monkeypatch.setattr("app.api.routes.health.database_is_ready", boom)
    with TestClient(app, raise_server_exceptions=False) as failing:
        response = failing.get(f"{settings.API_V1_STR}/health/ready/")

    assert response.status_code == 500
    _assert_headers(response.headers)
