"""Caching and precompressed variants for the built app (`app/core/static_cache.py`).

Hashed `/assets/*` files are immutable for a year; HTML documents (the app's `index.html` and the
SPA fallback for a deep link) are revalidated on every load; API responses are untouched; and every
one of them still carries the browser security headers.
"""

import gzip
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Headers

from app.core.security_headers import SECURITY_HEADERS, SecurityHeadersMiddleware
from app.core.static_cache import (
    IMMUTABLE,
    REVALIDATE,
    StaticCacheMiddleware,
    accepted_encodings,
    build_assets,
)
from app.main import app as main_app

SCRIPT = b"export const answer = 42;\n" * 64
# Not real Brotli (the standard library has no encoder); the middleware never decodes, it only
# chooses which file to send, so a recognisable payload is what the test needs.
SCRIPT_BR = b"pretend-brotli-bytes"
INDEX = b"<!doctype html><title>Clinic OS</title><div id=root></div>"


@pytest.fixture
def build(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_bytes(INDEX)
    (tmp_path / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (assets / "index-AbC123.js").write_bytes(SCRIPT)
    (assets / "index-AbC123.js.br").write_bytes(SCRIPT_BR)
    (assets / "index-AbC123.js.gz").write_bytes(gzip.compress(SCRIPT))
    (assets / "index-Zz9.css").write_text("body{margin:0}")
    (assets / "serif-latin-Q1.woff2").write_bytes(b"wOF2-font")
    return tmp_path


@pytest.fixture
def client(build: Path) -> Iterator[TestClient]:
    """The production stack in miniature: an API route, the app at `/`, the same middleware order."""
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    app.add_middleware(StaticCacheMiddleware, directory=build, api_prefix="/api")
    app.add_middleware(SecurityHeadersMiddleware)
    app.frontend("/", directory=build)
    with TestClient(app) as c:
        yield c


def _assert_security_headers(headers: Headers) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert value in headers.get_list(name), name


def test_a_hashed_asset_is_immutable_for_a_year(client: TestClient) -> None:
    response = client.get(
        "/assets/index-Zz9.css", headers={"accept-encoding": "identity"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE
    assert IMMUTABLE == "public, max-age=31536000, immutable"
    assert response.headers["content-type"].startswith("text/css")
    # No precompressed copy of this file, so the response cannot vary by encoding.
    assert "vary" not in response.headers
    assert "content-encoding" not in response.headers
    _assert_security_headers(response.headers)


def test_brotli_is_preferred_when_the_browser_accepts_it(client: TestClient) -> None:
    response = client.get(
        "/assets/index-AbC123.js", headers={"accept-encoding": "gzip, deflate, br"}
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "br"
    assert response.content == SCRIPT_BR
    assert response.headers["content-length"] == str(len(SCRIPT_BR))
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["cache-control"] == IMMUTABLE
    _assert_security_headers(response.headers)


def test_gzip_still_works_without_brotli(client: TestClient) -> None:
    response = client.get(
        "/assets/index-AbC123.js", headers={"accept-encoding": "gzip, br;q=0"}
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    # httpx decodes gzip: the browser gets back exactly the built file.
    assert response.content == SCRIPT
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["cache-control"] == IMMUTABLE


def test_no_accepted_encoding_gets_the_original_file(client: TestClient) -> None:
    response = client.get(
        "/assets/index-AbC123.js", headers={"accept-encoding": "identity"}
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.content == SCRIPT
    # The same URL has other representations, so caches must key on the header.
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["cache-control"] == IMMUTABLE


def test_a_head_request_matches_the_get(client: TestClient) -> None:
    response = client.head("/assets/index-AbC123.js", headers={"accept-encoding": "br"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "br"
    assert response.headers["content-length"] == str(len(SCRIPT_BR))
    assert response.headers["cache-control"] == IMMUTABLE


def test_a_revalidation_is_answered_304_with_the_same_policy(
    client: TestClient,
) -> None:
    first = client.get("/assets/index-AbC123.js", headers={"accept-encoding": "br"})
    again = client.get(
        "/assets/index-AbC123.js",
        headers={"accept-encoding": "br", "if-none-match": first.headers["etag"]},
    )

    assert again.status_code == 304
    assert again.headers["cache-control"] == IMMUTABLE
    assert again.headers["vary"] == "Accept-Encoding"


def test_a_font_is_immutable_and_never_recompressed(client: TestClient) -> None:
    response = client.get(
        "/assets/serif-latin-Q1.woff2", headers={"accept-encoding": "gzip, br"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE
    assert "content-encoding" not in response.headers


@pytest.mark.parametrize("path", ["/", "/index.html", "/patients/some-id"])
def test_the_html_document_is_always_revalidated(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"accept": "text/html"})

    assert response.status_code == 200
    assert response.content == INDEX
    assert response.headers["cache-control"] == REVALIDATE == "no-cache"
    _assert_security_headers(response.headers)


def test_a_missing_asset_is_never_cached_for_a_year(client: TestClient) -> None:
    fetched = client.get("/assets/index-Old000.js", headers={"accept": "*/*"})
    navigated = client.get("/assets/index-Old000.js", headers={"accept": "text/html"})

    assert fetched.status_code == 404
    assert "immutable" not in fetched.headers.get("cache-control", "")
    # A navigation gets the SPA fallback, which is a document like any other.
    assert navigated.status_code == 200
    assert navigated.headers["cache-control"] == REVALIDATE


def test_a_request_cannot_name_a_precompressed_file_of_its_own(
    client: TestClient,
) -> None:
    """Only the build's own names are rewritten; a crafted path gets no encoding."""
    response = client.get(
        "/assets/../index.html", headers={"accept-encoding": "br", "accept": "*/*"}
    )

    assert "content-encoding" not in response.headers


def test_api_responses_are_untouched(client: TestClient) -> None:
    response = client.get(
        "/api/v1/ping", headers={"accept-encoding": "gzip, br", "accept": "text/html"}
    )

    assert response.status_code == 200
    assert response.json() == {"pong": "yes"}
    assert "cache-control" not in response.headers
    assert "vary" not in response.headers
    assert "content-encoding" not in response.headers
    _assert_security_headers(response.headers)


def test_other_methods_pass_through(client: TestClient) -> None:
    response = client.post("/assets/index-AbC123.js")

    assert response.status_code == 405
    assert "cache-control" not in response.headers


def test_the_application_registers_it_inside_the_security_headers() -> None:
    classes: list[object] = [m.cls for m in main_app.user_middleware]

    assert StaticCacheMiddleware in classes
    # `user_middleware` lists the outermost first: the security headers wrap these responses.
    assert classes.index(SecurityHeadersMiddleware) < classes.index(
        StaticCacheMiddleware
    )


def test_the_applications_api_is_untouched() -> None:
    with TestClient(main_app) as c:
        response = c.get(
            "/api/v1/utils/health-check/", headers={"accept-encoding": "gzip, br"}
        )

    assert response.status_code == 200
    assert "cache-control" not in response.headers
    assert "content-encoding" not in response.headers


def test_build_assets_reads_names_and_their_variants(build: Path) -> None:
    assert build_assets(build / "assets") == {
        "index-AbC123.js": frozenset({"br", "gzip"}),
        "index-Zz9.css": frozenset(),
        "serif-latin-Q1.woff2": frozenset(),
    }
    assert build_assets(build / "no-such-dir") == {}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", set()),
        ("gzip, deflate, br, zstd", {"gzip", "deflate", "br", "zstd"}),
        ("br;q=0, gzip;q=0.5", {"gzip"}),
        ("BR ; Q=1.0", {"br"}),
        ("*", {"br", "gzip"}),
        ("*, br;q=0", {"gzip"}),
        ("*;q=0", set()),
        ("gzip;q=nonsense", set()),
    ],
)
def test_accept_encoding_parsing(header: str, expected: set[str]) -> None:
    assert accepted_encodings(header) == expected
