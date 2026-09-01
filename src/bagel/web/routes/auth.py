"""Auth routes — login / logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.services import auth as auth_svc
from bagel.storage.database import get_db
from bagel.web.templating import templates

router = APIRouter(tags=["auth"])


def _safe_next(raw: str | None) -> str:
    """Allow only same-origin relative paths (open-redirect safe)."""
    nxt = (raw or "/").strip() or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        return "/"
    return nxt


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse(url=_safe_next(request.query_params.get("next")), status_code=303)
    next_url = _safe_next(request.query_params.get("next"))
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "title": "登录",
            "nav": [],
            "active": "login",
            "error": None,
            "next_url": next_url,
        },
    )


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    next_url = _safe_next(next or request.query_params.get("next"))
    user = auth_svc.authenticate(db, username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": "登录",
                "nav": [],
                "active": "login",
                "error": "用户名或密码错误",
                "next_url": next_url,
            },
            status_code=401,
        )
    request.session["user_id"] = str(user.id)
    request.session["username"] = user.username
    request.session["is_admin"] = bool(user.is_admin)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/logout")
@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
