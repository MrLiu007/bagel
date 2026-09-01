"""Auth routes — login / logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.services import auth as auth_svc
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "登录", "nav": [], "active": "login", "error": None},
    )


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
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
            },
            status_code=401,
        )
    request.session["user_id"] = str(user.id)
    request.session["username"] = user.username
    request.session["is_admin"] = bool(user.is_admin)
    next_url = request.query_params.get("next") or "/"
    if not next_url.startswith("/"):
        next_url = "/"
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/logout")
@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
