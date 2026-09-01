"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from bagel import __version__
from bagel.settings import get_settings
from bagel.web.deps import NotAuthenticated
from bagel.web.nav import NAV_ITEMS
from bagel.web.routes.auth import router as auth_router
from bagel.web.routes.briefs import router as briefs_router
from bagel.web.routes.collect import router as collect_router
from bagel.web.routes.feishu import router as feishu_router
from bagel.web.routes.health import router as health_router
from bagel.web.routes.media import router as media_router
from bagel.web.routes.review import router as review_router
from bagel.web.routes.wechat import router as wechat_router
from bagel.web.templating import templates

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"

_PUBLIC_PREFIXES = (
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    import logging

    from bagel.jobs.scheduler import start_scheduler, stop_scheduler
    from bagel.storage.database import init_db

    log = logging.getLogger(__name__)
    try:
        init_db(seed=True)
    except Exception as exc:  # noqa: BLE001 — boot even if DB temporarily down
        log.warning("init_db failed: %s", exc)
    try:
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        log.warning("start_scheduler failed: %s", exc)
    yield
    try:
        stop_scheduler()
    except Exception as exc:  # noqa: BLE001
        log.warning("stop_scheduler failed: %s", exc)

def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Bagel（贝果）",
        version=__version__,
        lifespan=lifespan,
    )
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.include_router(auth_router)
    application.include_router(review_router)
    application.include_router(briefs_router)
    application.include_router(health_router)
    application.include_router(collect_router)
    application.include_router(media_router)
    application.include_router(wechat_router)
    application.include_router(feishu_router)

    @application.exception_handler(NotAuthenticated)
    async def _auth_redirect(_request: Request, exc: NotAuthenticated) -> RedirectResponse:
        nxt = quote(exc.next_url or "/", safe="/?=&")
        return RedirectResponse(url=f"/login?next={nxt}", status_code=303)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
            "storage": settings.storage_backend.value,
        }

    @application.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "title": "贝果",
                "version": __version__,
                "nav": NAV_ITEMS,
                "active": "home",
                "current_user": request.session.get("username"),
                "is_admin": request.session.get("is_admin"),
            },
        )

    # Middleware order: last added runs first. Session must wrap auth gate.
    from starlette.middleware.base import BaseHTTPMiddleware

    class AuthGateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if not settings.auth_required or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
                return await call_next(request)
            if request.session.get("user_id"):
                return await call_next(request)
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "未登录"}, status_code=401)
            nxt = quote(
                path + (f"?{request.url.query}" if request.url.query else ""),
                safe="/?=&",
            )
            return RedirectResponse(url=f"/login?next={nxt}", status_code=303)

    application.add_middleware(AuthGateMiddleware)
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="bagel_session",
        max_age=60 * 60 * 24 * 14,
        same_site="lax",
    )

    return application


app = create_app()
