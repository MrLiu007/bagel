"""Reverse-proxy path prefix (``X-Forwarded-Prefix`` / ``X-Script-Name``).

Nginx strips ``/bagel`` before forwarding; internal routes stay at ``/login`` etc.
This module sets ``scope["root_path"]`` so URL generation and redirects include the
public prefix when the proxy sends forwarding headers.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def root_path_from_scope(scope: Scope) -> str:
    raw = scope.get("root_path") or ""
    return raw.rstrip("/") if raw else ""


def app_url(request: Request | None, path: str) -> str:
    """Prefix an app-internal path with ``request.scope['root_path']`` when set."""
    if not path:
        return root_path_from_scope(request.scope) if request is not None else ""
    if not path.startswith("/") or path.startswith("//"):
        return path
    root = root_path_from_scope(request.scope) if request is not None else ""
    return f"{root}{path}" if root else path


class ForwardedPrefixMiddleware:
    """ASGI middleware: map proxy prefix headers to ``scope['root_path']``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            headers = dict(scope.get("headers") or [])
            prefix = (
                headers.get(b"x-forwarded-prefix", b"").decode("latin-1")
                or headers.get(b"x-script-name", b"").decode("latin-1")
            ).strip()
            if prefix:
                scope["root_path"] = prefix.rstrip("/")
        await self.app(scope, receive, send)


class PrefixLocationMiddleware(BaseHTTPMiddleware):
    """Rewrite ``Location`` headers on same-origin relative redirects."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        location = response.headers.get("location")
        if not location or not location.startswith("/") or location.startswith("//"):
            return response
        root = root_path_from_scope(request.scope)
        if not root:
            return response
        if location == root or location.startswith(f"{root}/"):
            return response
        response.headers["location"] = f"{root}{location}"
        return response
