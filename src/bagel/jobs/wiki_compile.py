"""Scheduled / manual wiki compile job (idempotent)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from bagel.services.wiki_compile import compile_wiki
from bagel.settings import get_settings


def run_compile_wiki(session: Session, *, limit: int = 400, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    # Always allow compile when called explicitly; WIKI_ENABLED gates auto-export elsewhere.
    result = compile_wiki(session, settings=settings, limit=limit, force=force)
    session.commit()
    return result
