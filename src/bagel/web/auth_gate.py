"""HTTP auth gate — session check before route handlers.

Design notes:
- HTML navigations without a session → 303 to ``/login?next=…``
- ``/api/*`` without a session → 401 JSON
- Browser / CDP probes (``/json/version``, favicon, …) → plain 404
  (never a login redirect — those probes hit whatever listens on the port
  and must not pollute logs with auth redirects)
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp

from bagel.settings import get_settings

# Paths that never require login (webhooks, health, static, login itself).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/login",
    "/logout",
    "/health",
    "/static",
    "/api/health",
    "/api/wechat/webhook",
    "/api/feishu/events",
    "/api/feishu/command",
    "/api/feishu/status",
)

# Chrome DevTools / Playwright / favicon probes — answer 404, never redirect.
_PROBE_EXACT: frozenset[str] = frozenset(
    {
        "/favicon.ico",
        "/robots.txt",
        "/json",
        "/json/version",
        "/json/list",
        "/json/protocol",
    }
)
_PROBE_PREFIXES: tuple[str, ...] = (
    "/.well-known/",
    "/json/",
)


def is_public_path(path: str) -> bool:
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


def is_probe_path(path: str) -> bool:
    if path in _PROBE_EXACT:
        return True
    return any(path.startswith(p) for p in _PROBE_PREFIXES)


def wants_html(request: Request) -> bool:
    """True when the client looks like a browser navigation (not XHR/API/CDP)."""
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        return True
    if accept in {"", "*/*"} and request.method in {"GET", "HEAD"}:
        # Browsers often send */* for top-level navigations; CDP probes usually
        # send no Accept or application/json — treat bare GET as HTML-capable.
        sec_fetch = (request.headers.get("sec-fetch-mode") or "").lower()
        if sec_fetch in {"navigate", ""}:
            return True
    return False


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Enforce login for HTML pages and APIs when ``AUTH_REQUIRED=true``."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if is_probe_path(path):
            return Response(status_code=404)

        settings = get_settings()
        if not settings.auth_required or is_public_path(path):
            return await call_next(request)

        if request.session.get("user_id"):
            return await call_next(request)

        if path.startswith("/api/") or not wants_html(request):
            return JSONResponse({"detail": "未登录"}, status_code=401)

        nxt = quote(
            path + (f"?{request.url.query}" if request.url.query else ""),
            safe="/?=&",
        )
        return RedirectResponse(url=f"/login?next={nxt}", status_code=303)
