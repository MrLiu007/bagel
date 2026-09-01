"""Phase 7: network checks, doctor CLI text, health page."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.models import Base
from bagel.main import create_app
from bagel.services.health import (
    CheckResult,
    HealthReport,
    format_doctor_report,
    run_health_checks,
)
from bagel.settings import NetworkMode, Settings
from bagel.storage.database import get_db, get_engine, get_session_factory


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'p7.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_format_doctor_report_degraded() -> None:
    report = HealthReport(
        checks=[
            CheckResult(name="Database", ok=True, message="connected"),
            CheckResult(name="GitHub API", ok=False, message="unreachable", degraded=True),
            CheckResult(name="China Network", ok=True, message="ok"),
        ],
        can_run=True,
    )
    text = format_doctor_report(report)
    assert "Bagel Doctor" in text
    assert "[OK] Database" in text
    assert "[WARN] GitHub API" in text
    assert "host.docker.internal" in text
    assert "degraded mode" in text.lower()


def test_run_health_checks_with_mocked_probes(db: Session) -> None:
    settings = Settings(
        network_mode=NetworkMode.AUTO,
        rsshub_base_url="http://rsshub:1200",
        freshrss_base_url="http://freshrss",
        llm_enabled=False,
    )

    def fake_probe(url: str, *, settings, force_proxy=None, timeout=8.0):
        if "baidu" in url:
            return True, "HTTP 200", 200
        if "github" in url:
            return False, "network unreachable", None
        if "openai" in url:
            return False, "timeout", None
        if "rsshub" in url or "freshrss" in url:
            return True, "HTTP 200", 200
        return False, "unknown", None

    with patch("bagel.services.health._probe_url", side_effect=fake_probe):
        report = run_health_checks(db, settings)

    names = {c.name: c for c in report.checks}
    assert names["Database"].ok is True
    assert names["China Network"].ok is True
    assert names["GitHub API"].ok is False
    assert names["GitHub API"].degraded is True
    assert report.can_run is True


def test_settings_health_page(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    from bagel.settings import get_settings

    get_settings.cache_clear()
    app = create_app()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with patch("bagel.web.routes.health.run_health_checks") as mocked:
        mocked.return_value = HealthReport(
            checks=[
                CheckResult(name="Database", ok=True, message="connected"),
                CheckResult(name="GitHub API", ok=False, message="unreachable", degraded=True),
            ],
            can_run=True,
        )
        with TestClient(app) as client:
            resp = client.get("/settings/health")
            assert resp.status_code == 200
            assert "系统状态" in resp.text
            assert "Database" in resp.text
            assert "GitHub API" in resp.text
            assert "降级" in resp.text
    app.dependency_overrides.clear()
    get_settings.cache_clear()
