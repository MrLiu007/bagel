"""Reddit headers, scheduler jitter config, CLI runtime, Feishu webhook."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.models import Base
from bagel.integrations.cli_runtime import resolve_binary, run_command
from bagel.integrations.http import request_headers_for_url
from bagel.jobs.scheduler import reload_scheduler_jobs, scheduler_status, stop_scheduler
from bagel.main import create_app
from bagel.services.runtime_config import (
    SCHEDULE_INTERVAL_OPTIONS,
    RuntimeConfig,
    load_runtime_config,
    save_runtime_config,
)
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.seed import DEFAULT_REDDIT_SOURCES, ensure_reddit_sources


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'sched.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    from bagel.settings import get_settings

    get_settings.cache_clear()
    stop_scheduler()
    app = create_app()

    def _override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    stop_scheduler()
    get_settings.cache_clear()


def test_reddit_headers_are_browser_like():
    hdrs = request_headers_for_url("https://www.reddit.com/r/MachineLearning/new/.rss")
    assert "Mozilla" in hdrs["User-Agent"]
    assert hdrs["Sec-Fetch-Mode"] == "navigate"
    assert "Accept-Language" in hdrs


def test_non_reddit_keeps_app_ua():
    hdrs = request_headers_for_url("https://www.jiqizhixin.com/rss")
    assert "Bagel" in hdrs["User-Agent"]


def test_default_reddit_sources_present():
    assert len(DEFAULT_REDDIT_SOURCES) >= 3
    assert all("reddit.com" in r["url"] for r in DEFAULT_REDDIT_SOURCES)


def test_ensure_reddit_sources_idempotent(db: Session):
    n1 = ensure_reddit_sources(db)
    assert n1 >= 3
    n2 = ensure_reddit_sources(db)
    assert n2 == 0


def test_runtime_config_interval_options(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from bagel.settings import get_settings

    get_settings.cache_clear()
    assert 30 in SCHEDULE_INTERVAL_OPTIONS
    assert 720 in SCHEDULE_INTERVAL_OPTIONS
    cfg = save_runtime_config(
        RuntimeConfig(
            enable_scheduler=True,
            schedule_interval_minutes=45,  # invalid → normalized to 30
            schedule_jitter_seconds=120,
        )
    )
    assert cfg.schedule_interval_minutes == 30
    assert cfg.schedule_jitter_seconds == 120
    loaded = load_runtime_config()
    assert loaded.enable_scheduler is True
    get_settings.cache_clear()


def test_scheduler_reload_starts_and_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from bagel.settings import get_settings

    get_settings.cache_clear()
    stop_scheduler()
    save_runtime_config(
        RuntimeConfig(
            enable_scheduler=True,
            schedule_interval_minutes=60,
            schedule_jitter_seconds=90,
            schedule_collect_news=True,
            schedule_collect_github=False,
            schedule_collect_stocks=False,
        )
    )
    st = reload_scheduler_jobs()
    assert st["running"] is True
    assert st["interval_minutes"] == 60
    assert st["jitter_seconds"] == 90
    assert any(j["id"] == "collect_news" for j in st["jobs"])
    save_runtime_config(RuntimeConfig(enable_scheduler=False))
    st2 = reload_scheduler_jobs()
    assert st2["running"] is False
    stop_scheduler()
    get_settings.cache_clear()


def test_cli_run_command_echo():
    # Portable no-op: python -c
    import sys

    result = run_command([sys.executable, "-c", "print('ok-cli')"], timeout=10)
    assert result.ok
    assert "ok-cli" in result.stdout


def test_resolve_binary_missing():
    bin_info = resolve_binary("definitely-not-a-real-cli-zzzz")
    assert bin_info.found is False


def test_feishu_webhook_send(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from bagel.settings import get_settings

    get_settings.cache_clear()
    save_runtime_config(
        RuntimeConfig(
            enable_feishu_cli=True,
            feishu_webhook_url="https://example.com/hook",
        )
    )

    class FakeResp:
        status_code = 200
        text = '{"StatusCode":0}'

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            assert "hook" in url
            assert json["msg_type"] == "text"
            return FakeResp()

    with patch("bagel.integrations.feishu_cli.build_http_client", return_value=FakeClient()):
        from bagel.integrations import feishu_cli

        result = feishu_cli.send_text("hello")
        assert result.ok
    get_settings.cache_clear()


def test_settings_schedule_and_cli_pages(client: TestClient):
    r1 = client.get("/settings?tab=schedule")
    assert r1.status_code == 200
    assert "定时" in r1.text or "拉取间隔" in r1.text
    r2 = client.get("/settings?tab=cli")
    assert r2.status_code == 200
    assert "飞书" in r2.text

    resp = client.post(
        "/settings/schedule",
        data={
            "enable_scheduler": "1",
            "schedule_interval_minutes": "120",
            "schedule_jitter_seconds": "120",
            "schedule_collect_news": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    st = scheduler_status()
    assert st["enabled"] is True
    assert st["interval_minutes"] == 120
    # cleanup
    client.post(
        "/settings/schedule",
        data={
            "schedule_interval_minutes": "30",
            "schedule_jitter_seconds": "120",
        },
        follow_redirects=False,
    )
    stop_scheduler()
