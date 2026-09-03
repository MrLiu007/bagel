"""Model hub collectors + /models UI wiring."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bagel.collectors.models import (
    COMMUNITY_HUGGINGFACE,
    COMMUNITY_MODELSCOPE,
    ModelRecord,
    fetch_from_source,
)
from bagel.domain.enums import BriefKind, ItemType, SourceType
from bagel.jobs.models import run_collect_models
from bagel.main import create_app
from bagel.services.monthly_templates import item_types_for_kind
from bagel.settings import get_settings
from bagel.storage.seed import DEFAULT_MODEL_SOURCES


def test_default_model_sources_cover_hf_and_ms() -> None:
    urls = {str(r["url"]) for r in DEFAULT_MODEL_SOURCES}
    assert urls == {"hf:models", "ms:models"}
    assert all(r["source_type"] == SourceType.MODEL for r in DEFAULT_MODEL_SOURCES)
    assert len(DEFAULT_MODEL_SOURCES) == 2


def test_fetch_from_source_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_hf(**kwargs):
        calls.append("hf")
        return [
            ModelRecord(
                title="org/demo",
                url="https://huggingface.co/org/demo",
                summary="demo",
                author="org",
                published_at=None,
                community=COMMUNITY_HUGGINGFACE,
                external_id="hf:org/demo",
                model_id="org/demo",
            )
        ]

    def fake_ms(**kwargs):
        calls.append("ms")
        return [
            ModelRecord(
                title="demo",
                url="https://www.modelscope.cn/models/org/demo",
                summary="demo",
                author="org",
                published_at=None,
                community=COMMUNITY_MODELSCOPE,
                external_id="ms:org/demo",
                model_id="org/demo",
            )
        ]

    monkeypatch.setattr("bagel.collectors.models.fetch_huggingface_models", fake_hf)
    monkeypatch.setattr("bagel.collectors.models.fetch_modelscope_models", fake_ms)
    assert fetch_from_source("HF", "hf:models:downloads")[0].community == COMMUNITY_HUGGINGFACE
    assert fetch_from_source("魔搭", "ms:models:search:Qwen")[0].community == COMMUNITY_MODELSCOPE
    assert calls == ["hf", "ms"]


def test_run_collect_models_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    src = MagicMock()
    src.id = "11111111-1111-1111-1111-111111111111"
    src.name = "HF"
    src.url = "hf:models"
    src.last_error_code = None

    session = MagicMock()
    session.scalars.return_value.all.return_value = [src]

    created_flags = {"n": 0}

    def fake_upsert(**kwargs):
        created_flags["n"] += 1
        assert kwargs.get("owner_id") is not None
        item = MagicMock()
        item.llm_why = None
        return item, True

    repo = MagicMock()
    repo.upsert_from_normalized.side_effect = fake_upsert

    monkeypatch.setattr(
        "bagel.jobs.models.fetch_from_source",
        lambda name, url: [
            ModelRecord(
                title="org/m",
                url="https://huggingface.co/org/m",
                summary="s",
                author="org",
                published_at=datetime.now(UTC),
                community=COMMUNITY_HUGGINGFACE,
                external_id="hf:org/m",
                model_id="org/m",
                downloads=10,
            )
        ],
    )
    monkeypatch.setattr("bagel.jobs.models.ItemRepository", lambda session: repo)
    monkeypatch.setattr("bagel.jobs.models.wiki_svc.export_item", lambda *a, **k: None)

    result = run_collect_models(session, owner_id="22222222-2222-2222-2222-222222222222")
    assert result["status"] == "SUCCESS"
    assert result["items_created"] == 1
    assert result["source_stats"][0]["status"] == "success"
    assert created_flags["n"] == 1


def test_dedupe_model_sources() -> None:
    from unittest.mock import MagicMock

    from bagel.storage.seed import dedupe_model_sources

    def _src(url: str, *, name: str, enabled: bool = True, priority: int = 10):
        s = MagicMock()
        s.id = MagicMock()
        s.url = url
        s.name = name
        s.enabled = enabled
        s.priority = priority
        s.source_type = SourceType.MODEL
        return s

    keep = _src("hf:models", name="Hugging Face · 最近更新", priority=10)
    dup = _src("hf:models", name="HF dup", priority=20)
    obsolete = _src("hf:models:downloads", name="HF downloads", priority=30)
    ms = _src("ms:models", name="ModelScope 魔搭 · 最近更新", priority=40)

    session = MagicMock()
    session.scalars.return_value.all.return_value = [keep, dup, obsolete, ms]
    deleted = dedupe_model_sources(session)
    assert deleted == 2
    assert keep.name == "Hugging Face"
    assert ms.name == "ModelScope 魔搭"
    assert session.delete.call_count == 2
    assert session.execute.call_count == 2


def test_models_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        models = client.get("/models")
        assert models.status_code == 200
        assert "模型" in models.text
        assert "全部社区" in models.text or "Hugging Face" in models.text

        settings = client.get("/settings?tab=models")
        assert settings.status_code == 200
        assert "模型数据源" in settings.text
        assert "hf:models" in settings.text

        briefs = client.get("/briefs/models")
        assert briefs.status_code == 200
        assert "模型总结" in briefs.text
    finally:
        get_settings.cache_clear()
