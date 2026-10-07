"""Browser security headers on every HTTP response the backend sends.

The backend serves the API, the API docs and the built app at `/`, so it is the host that
`docs2/architecture.md` ("Security measures in the app") says must refuse framing:
`frame-ancestors` is ignored in a `<meta>` policy, so clickjacking protection exists only as a
response header. `docs/tasks/01-phase-1-foundations.md` T1-42 adds HSTS, `X-Content-Type-Options`
and `Referrer-Policy` to "every response".

- `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` - nobody frames
  the app, the docs or an API answer (the second for browsers without CSP level 2).
- `X-Content-Type-Options: nosniff` - a response is only ever what its declared type says.
- `Referrer-Policy: no-referrer` - the same policy `frontend/index.html` declares in a `<meta>`.
- `Strict-Transport-Security: max-age=31536000` - browsers ignore it over plain HTTP, so local
  work is unaffected; behind TLS it pins the host to HTTPS. No `includeSubDomains`: the backend
  does not own its parent domain's other hosts.

The policy here restricts framing and nothing else, so it does not interfere with the app's own
build-time policy (`frontend/vite.config.ts`) or with Swagger UI's CDN assets on `/docs`. A
response that sends its own `Content-Security-Policy` keeps it and still gets this one: a browser
enforces every policy it receives, so a route can tighten the policy but never drop
`frame-ancestors`. The other headers are set only where the response has not set them.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = "Content-Security-Policy"

SECURITY_HEADERS: dict[str, str] = {
    CONTENT_SECURITY_POLICY: "frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
}


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware, so a streamed or static response is not buffered to add a header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name == CONTENT_SECURITY_POLICY:
                        headers.append(name, value)
                    elif name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
