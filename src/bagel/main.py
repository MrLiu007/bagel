"""FastAPI application entry point.

`create_app()` wires routes, session auth, and lifespan hooks that:
1. init / seed the DB (degraded boot if DB is temporarily down)
2. optionally clone MediaCrawler into `third_party/` (gitignored)
3. start the in-process APScheduler when enabled in runtime config
"""

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
from bagel.web.auth_gate import AuthGateMiddleware
from bagel.web.proxy_prefix import ForwardedPrefixMiddleware, PrefixLocationMiddleware
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

_QUIET_ACCESS_MARKERS: tuple[str, ...] = (
    "/json/version",
    "/json/list",
    '"GET /json ',
    "/favicon.ico",
    "/robots.txt",
    "/.well-known/",
)


def _install_quiet_access_log() -> None:
    """Hide IDE/browser probe noise from uvicorn access logs (reload-safe)."""
    import logging

    class _QuietProbeFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                return True
            return not any(marker in msg for marker in _QUIET_ACCESS_MARKERS)

    log = logging.getLogger("uvicorn.access")
    if any(isinstance(f, _QuietProbeFilter) for f in log.filters):
        return
    log.addFilter(_QuietProbeFilter())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    import logging

    from bagel.jobs.scheduler import start_scheduler, stop_scheduler
    from bagel.services.media_setup import ensure_mediacrawler_on_startup
    from bagel.storage.database import init_db

    log = logging.getLogger(__name__)
    try:
        init_db(seed=True)
    except Exception as exc:  # noqa: BLE001 — boot even if DB temporarily down
        log.warning("init_db failed: %s", exc)
    try:
        # Keeps git repo small: MediaCrawler is gitignored and cloned on first boot if missing.
        ensure_mediacrawler_on_startup()
    except Exception as exc:  # noqa: BLE001
        log.warning("mediacrawler ensure failed: %s", exc)
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
    _install_quiet_access_log()
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

    # Middleware order: last added runs first (outermost).
    # ForwardedPrefix must run first on request; PrefixLocation must wrap AuthGate responses.
    application.add_middleware(AuthGateMiddleware)
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="bagel_session",
        max_age=60 * 60 * 24 * 14,
        same_site="lax",
    )
    application.add_middleware(PrefixLocationMiddleware)
    application.add_middleware(ForwardedPrefixMiddleware)

    return application


app = create_app()
