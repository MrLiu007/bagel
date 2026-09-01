"""Request auth helpers."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from bagel.domain.models import AppUser
from bagel.services import auth as auth_svc
from bagel.settings import get_settings
from bagel.storage.database import get_db


class NotAuthenticated(Exception):
    """Raised when login is required for an HTML page."""

    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> AppUser | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = auth_svc.get_user_by_id(db, uid)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    settings = get_settings()
    user = get_optional_user(request, db)
    if user is not None:
        return user
    if not settings.auth_required:
        # Dev escape hatch: ensure default admin exists and auto-bind.
        user = auth_svc.ensure_default_admin(db)
        request.session["user_id"] = str(user.id)
        request.session["username"] = user.username
        request.session["is_admin"] = bool(user.is_admin)
        return user
    raise NotAuthenticated(next_url=str(request.url.path))


def require_admin(user: AppUser = Depends(require_user)) -> AppUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def owner_id_or_none(user: AppUser | None) -> uuid.UUID | None:
    return user.id if user is not None else None
