"""Phase 1 unit tests: settings, health, CLI wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.settings import Settings, NetworkMode


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


def test_home_page() -> None:
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert "贝果" in resp.text
