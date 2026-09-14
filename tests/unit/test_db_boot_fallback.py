"""Boot resilience: short Postgres timeout + SQLite fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bagel.settings import DEFAULT_SQLITE_URL
from bagel.storage import database as db


def test_postgres_engine_sets_connect_timeout(monkeypatch) -> None:
    db.reset_engine()
    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["connect_args"] = kwargs.get("connect_args") or {}
        captured["pool_timeout"] = kwargs.get("pool_timeout")
        eng = MagicMock()
        eng.dialect.name = "postgresql"
        return eng

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    eng = db.get_engine("postgresql+psycopg://u:p@127.0.0.1:5432/bagel")
    assert eng is not None
    assert captured["connect_args"].get("connect_timeout") == 3
    assert captured["pool_timeout"] == 3.0
    db.reset_engine()


def test_init_db_resilient_falls_back_to_sqlite(monkeypatch, tmp_path) -> None:
    db.reset_engine()
    sqlite_url = f"sqlite+pysqlite:///{(tmp_path / 'boot.db').as_posix()}"

    settings = MagicMock()
    settings.is_dev = True
    settings.app_env = "development"
    settings.resolved_database_url = "postgresql+psycopg://u:p@127.0.0.1:65432/bagel"

    calls = {"n": 0}

    def fake_probe(engine=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("connection timeout expired")

    monkeypatch.setattr(db, "get_settings", lambda: settings)
    monkeypatch.setattr(db, "probe_db", fake_probe)
    monkeypatch.setattr(db, "init_db", lambda seed=True: None)
    monkeypatch.setattr(db, "DEFAULT_SQLITE_URL", sqlite_url)

    created: list[str] = []

    def fake_get_engine(url=None, *, echo=False):
        active = url or db._active_database_url or settings.resolved_database_url
        created.append(active)
        return MagicMock()

    monkeypatch.setattr(db, "get_engine", fake_get_engine)

    info = db.init_db_resilient(seed=True, fallback_sqlite=True)
    assert info["fallback"] == "1"
    assert info["backend"] == "sqlite"
    assert db._active_database_url == sqlite_url
    db.reset_engine()


def test_init_db_resilient_no_fallback_when_disabled(monkeypatch) -> None:
    db.reset_engine()
    settings = MagicMock()
    settings.is_dev = False
    settings.app_env = "production"
    settings.resolved_database_url = "postgresql+psycopg://u:p@127.0.0.1:65432/bagel"

    monkeypatch.setattr(db, "get_settings", lambda: settings)
    monkeypatch.setattr(db, "get_engine", lambda url=None, echo=False: MagicMock())
    monkeypatch.setattr(
        db,
        "probe_db",
        lambda engine=None: (_ for _ in ()).throw(TimeoutError("connection timeout expired")),
    )

    with pytest.raises(TimeoutError):
        db.init_db_resilient(seed=False, fallback_sqlite=False)
    db.reset_engine()


def test_is_db_unreachable_recognizes_psycopg_timeout() -> None:
    assert db._is_db_unreachable(TimeoutError("connection timeout expired"))
    assert db._is_db_unreachable(Exception("psycopg.errors.ConnectionTimeout"))
    assert not db._is_db_unreachable(ValueError("bad schema"))
    # silence unused import in some linters
    assert DEFAULT_SQLITE_URL.startswith("sqlite")
