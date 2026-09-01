"""Phase 9: MVP acceptance smoke checks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.models import Base
from bagel.main import create_app
from bagel.storage.database import get_db, get_engine, get_session_factory

ROOT = Path(__file__).resolve().parents[2]


def test_required_project_files_exist() -> None:
    for rel in [
        "compose.yml",
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        ".env.example",
        "README.md",
        "AGENTS.md",
        "alembic.ini",
        "docs/architecture.md",
        "docs/data-model.md",
        "docs/network.md",
    ]:
        assert (ROOT / rel).exists(), rel


def test_readme_is_one_page_start() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose up -d" in text
    assert "http://localhost:8000" in text
    assert "uv run bagel doctor" in text
    assert "HTTPS_PROXY" in text


def test_openapi_exposes_mvp_routes() -> None:
    paths = set(create_app().openapi()["paths"].keys())
    for path in [
        "/health",
        "/",
        "/candidates",
        "/news",
        "/github",
        "/releases",
        "/favorites",
        "/ignored",
        "/digests",
        "/briefs/news",
        "/briefs/github",
        "/settings",
        "/settings/health",
        "/items/{item_id}/action",
    ]:
        assert path in paths, path


def test_home_and_health_ok() -> None:
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    home = client.get("/")
    assert home.status_code == 200
    assert "情报" in home.text or "Intel" in home.text


def test_candidates_page_with_sqlite(tmp_path) -> None:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'p9.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    app = create_app()

    def _override():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        resp = client.get("/news")
        assert resp.status_code == 200
        assert "暂无" in resp.text or "新闻" in resp.text
        settings = client.get("/settings")
        assert settings.status_code == 200
        assert "过滤标签" in settings.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_env_example_covers_required_keys() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in [
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "LLM_BASE_URL",
        "RSSHUB_BASE_URL",
        "FRESHRSS_BASE_URL",
        "NETWORK_MODE",
        "HTTPS_PROXY",
        "ENABLE_GITHUB",
        "ENABLE_LLM_SUMMARY",
    ]:
        assert key in env
