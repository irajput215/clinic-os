"""Cache headers and precompressed variants for the built app the backend serves at `/`.

`bun run build` writes the app to `app/frontend/`: an `index.html` that names every script and
stylesheet by a content-hashed file under `assets/`, and those hashed files. So:

- `/assets/*` never changes under its name. It is sent with
  `Cache-Control: public, max-age=31536000, immutable`, and a browser that has it never asks again.
- An HTML document (`/`, `/index.html`, the SPA fallback for a deep link such as `/patients/<id>`)
  must be revalidated on every load, or a returning browser keeps an `index.html` that names assets
  a newer deploy has replaced. It is sent with `Cache-Control: no-cache` (stored, but always
  revalidated; the static server answers a matching `If-None-Match` with `304`).
- The build also writes a Brotli (`.br`) and a gzip (`.gz`) copy beside each compressible asset
  (`frontend/vite.config.ts`, `precompress`). A request whose `Accept-Encoding` allows one is served
  that file with `Content-Encoding` and `Vary: Accept-Encoding`; anything else gets the original.
  Nothing is compressed per request, and no compression library is added.

API responses are never touched: a path under the API prefix passes straight through, so their
caching stays whatever the route says. A failed asset request (`404`) is not marked immutable.

The asset names are read from the build directory once, when the app starts. Only those names are
marked immutable or rewritten to a precompressed file, so a request path never selects a file of
its own making, and a missing asset that the SPA fallback answers with `index.html` is treated as
the document it is (`no-cache`), never cached for a year. A rebuild therefore needs a restart, as
serving the app already does (`HOW_TO_RUN.md`); until then a new name is simply not cached.

Pure ASGI, so a file response is streamed, not buffered, to add a header. Register it inside
`SecurityHeadersMiddleware`, so the rewritten responses carry the security headers too.
"""

import mimetypes
import os
from collections.abc import Mapping
from pathlib import Path

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
ASSETS_PREFIX = "/assets/"

# Preference order: Brotli is smaller than gzip for the same file.
ENCODINGS: tuple[tuple[str, str], ...] = (("br", ".br"), ("gzip", ".gz"))
_SUFFIXES = tuple(suffix for _, suffix in ENCODINGS)


def build_assets(assets_dir: Path) -> dict[str, frozenset[str]]:
    """Each built asset's file name -> the encodings a precompressed sibling exists for."""
    if not assets_dir.is_dir():
        return {}
    names = {entry.name for entry in os.scandir(assets_dir) if entry.is_file()}
    assets: dict[str, frozenset[str]] = {}
    for name in names:
        if name.endswith(_SUFFIXES):
            continue
        assets[name] = frozenset(
            encoding for encoding, suffix in ENCODINGS if name + suffix in names
        )
    return assets


def accepted_encodings(accept_encoding: str) -> set[str]:
    """The content codings `Accept-Encoding` allows (`q=0` refuses one; `*` allows any)."""
    accepted: set[str] = set()
    refused: set[str] = set()
    wildcard = False
    for item in accept_encoding.split(","):
        token, _, params = item.strip().partition(";")
        coding = token.strip().lower()
        if not coding:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if coding == "*":
            wildcard = quality > 0
        elif quality > 0:
            accepted.add(coding)
        else:
            refused.add(coding)
    if wildcard:
        accepted |= {encoding for encoding, _ in ENCODINGS} - refused
    return accepted


class StaticCacheMiddleware:
    def __init__(
        self, app: ASGIApp, *, directory: Path, api_prefix: str = "/api"
    ) -> None:
        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self.assets: Mapping[str, frozenset[str]] = build_assets(
            directory / ASSETS_PREFIX.strip("/")
        )

    def _is_api(self, path: str) -> bool:
        return path == self.api_prefix or path.startswith(self.api_prefix + "/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in ("GET", "HEAD")
            or self._is_api(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path.startswith(ASSETS_PREFIX) and path[len(ASSETS_PREFIX) :] in self.assets:
            await self._asset(scope, receive, send)
            return

        async def send_document(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if (
                    headers.get("content-type", "").startswith("text/html")
                    and "cache-control" not in headers
                ):
                    headers["Cache-Control"] = REVALIDATE
            await send(message)

        await self.app(scope, receive, send_document)

    async def _asset(self, scope: Scope, receive: Receive, send: Send) -> None:
        name = scope["path"][len(ASSETS_PREFIX) :]
        available = self.assets[name]
        encoding: str | None = None
        if available:
            accepted = accepted_encodings(
                Headers(scope=scope).get("accept-encoding", "")
            )
            encoding = next(
                (e for e, _ in ENCODINGS if e in available and e in accepted), None
            )
        if encoding is not None:
            suffix = dict(ENCODINGS)[encoding]
            scope = dict(scope)
            scope["path"] = scope["path"] + suffix
            scope["raw_path"] = scope["path"].encode()
        media_type = mimetypes.guess_type(name)[0]

        async def send_asset(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] in (
                200,
                206,
                304,
            ):
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = IMMUTABLE
                if available:
                    headers.add_vary_header("Accept-Encoding")
                if encoding is not None and message["status"] != 304:
                    headers["Content-Encoding"] = encoding
                    if media_type is not None:
                        headers["Content-Type"] = _with_charset(media_type)
            await send(message)

        await self.app(scope, receive, send_asset)


def _with_charset(media_type: str) -> str:
    """The `Content-Type` the static server sends for the uncompressed file."""
    if media_type.startswith("text/"):
        return f"{media_type}; charset=utf-8"
    return media_type
