"""User authentication and password hashing (stdlib PBKDF2)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.models import AppUser

PBKDF2_ROUNDS = 120_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt, digest_hex = encoded.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


@dataclass
class AuthUser:
    id: uuid.UUID
    username: str
    is_admin: bool
    is_active: bool


def to_auth_user(user: AppUser) -> AuthUser:
    return AuthUser(
        id=user.id,
        username=user.username,
        is_admin=bool(user.is_admin),
        is_active=bool(user.is_active),
    )


def get_user_by_id(session: Session, user_id: uuid.UUID | str) -> AppUser | None:
    try:
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None
    return session.get(AppUser, uid)


def get_user_by_username(session: Session, username: str) -> AppUser | None:
    return session.scalar(select(AppUser).where(AppUser.username == username.strip()))


def authenticate(session: Session, username: str, password: str) -> AppUser | None:
    user = get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def list_users(session: Session) -> list[AppUser]:
    return list(session.scalars(select(AppUser).order_by(AppUser.username)).all())


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    is_admin: bool = False,
) -> AppUser:
    username = username.strip()
    if not username or not password:
        raise ValueError("用户名和密码不能为空")
    if get_user_by_username(session, username):
        raise ValueError("用户名已存在")
    user = AppUser(
        username=username,
        password_hash=hash_password(password),
        is_admin=is_admin,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def update_password(session: Session, user: AppUser, password: str) -> AppUser:
    if not password:
        raise ValueError("密码不能为空")
    user.password_hash = hash_password(password)
    session.flush()
    return user


def set_active(session: Session, user: AppUser, active: bool) -> AppUser:
    user.is_active = active
    session.flush()
    return user


def ensure_default_admin(session: Session) -> AppUser:
    """Seed default account liuzemin / 123456 if no users exist."""
    existing = session.scalar(select(AppUser).limit(1))
    if existing is not None:
        admin = get_user_by_username(session, "liuzemin")
        return admin or existing
    return create_user(session, username="liuzemin", password="123456", is_admin=True)
