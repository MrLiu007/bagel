"""Alembic revision graph — app_user must precede wiki_page FKs."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from bagel.settings import get_settings
from bagel.storage import database as dbmod

ROOT = Path(__file__).resolve().parents[2]


def test_app_user_revision_before_wiki_index() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    wiki = script.get_revision("0006_wiki_index")
    assert wiki is not None
    assert wiki.down_revision == "0005a_app_user"
    app_user = script.get_revision("0005a_app_user")
    assert app_user is not None
    assert app_user.down_revision == "0005_search_event"
    # walk_revisions is newest-first
    ids = [rev.revision for rev in script.walk_revisions()]
    assert ids.index("0006_wiki_index") < ids.index("0005a_app_user")
    assert ids.index("0005a_app_user") < ids.index("0005_search_event")


def test_ensure_schema_creates_missing_tables(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "ensure.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    get_settings.cache_clear()
    dbmod._engine = None
    dbmod._SessionLocal = None

    dbmod.ensure_schema()
    engine = dbmod.get_engine()
    names = set(inspect(engine).get_table_names())
    assert "app_user" in names
    assert "wiki_page" in names
    assert "wiki_edge" in names
    assert "gbrain_learn_event" in names
    assert "intel_item" in names

    # Idempotent second call
    dbmod.ensure_schema()
    assert set(inspect(engine).get_table_names()) == names
    get_settings.cache_clear()
