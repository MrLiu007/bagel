"""Phase 1 unit tests: settings, health, CLI wiring."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.settings import NetworkMode, Settings, get_settings


def test_settings_defaults() -> None:
    s = Settings(
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.app_port == 8000
    assert s.network_mode == NetworkMode.AUTO
    assert s.enable_github is True
    assert s.storage_backend.value == "sqlite"
    assert s.resolved_database_url.startswith("sqlite")


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_home_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/")
        assert resp.status_code == 200
        assert "贝果" in resp.text
    finally:
        get_settings.cache_clear()
