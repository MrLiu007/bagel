"""Manual / scheduled collect task UI + progress API."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.services.tasks import TaskManager, task_manager
from bagel.settings import get_settings


def test_task_manager_progress_and_success() -> None:
    mgr = TaskManager()

    def fake_news(session, on_progress=None, cn_only=False, settings=None):
        if on_progress:
            on_progress(current=0, total=2, message="start")
            on_progress(current=1, total=2, message="mid")
            on_progress(current=2, total=2, message="done")
        return {
            "items_found": 2,
            "items_created": 1,
            "status": "SUCCESS",
            "source_stats": [
                {
                    "name": "demo",
                    "status": "success",
                    "items_found": 2,
                    "items_created": 1,
                    "items_updated": 0,
                    "items_skipped": 0,
                    "duration_ms": 12,
                }
            ],
            "duration_ms": 20,
        }

    with patch("bagel.jobs.news.run_collect_news", side_effect=fake_news), patch(
        "bagel.services.tasks.get_engine"
    ), patch("bagel.services.tasks.get_session_factory") as factory:
        session = factory.return_value.return_value
        session.commit = lambda: None
        session.rollback = lambda: None
        session.close = lambda: None
        state = mgr.start("collect_news", options={"cn_only": True})
        for _ in range(50):
            cur = mgr.get(state.id)
            assert cur is not None
            if cur.status in {"success", "failed"}:
                break
            time.sleep(0.05)
        done = mgr.get(state.id)
        assert done is not None
        assert done.status == "success"
        assert done.percent == 100.0
        assert done.trigger == "manual"
        assert done.result["items_created"] == 1
        assert done.result["source_stats"][0]["name"] == "demo"
        assert done.to_dict()["duration_ms"] == 20


def test_record_completed_scheduled() -> None:
    mgr = TaskManager()
    state = mgr.record_completed(
        "collect_news",
        trigger="scheduled",
        result={
            "status": "PARTIAL",
            "items_found": 10,
            "items_created": 3,
            "items_updated": 1,
            "items_skipped": 6,
            "duration_ms": 1500,
            "source_stats": [
                {
                    "name": "rss-a",
                    "status": "success",
                    "items_created": 3,
                    "items_updated": 1,
                    "items_skipped": 6,
                    "items_found": 10,
                    "duration_ms": 1400,
                }
            ],
        },
    )
    assert state.trigger == "scheduled"
    assert state.status == "success"
    recent = mgr.list_recent(5, trigger="scheduled")
    assert any(t.id == state.id for t in recent)
    assert not any(t.id == state.id for t in mgr.list_recent(5, trigger="manual"))


def test_collect_routes_registered() -> None:
    paths = set(create_app().openapi()["paths"].keys())
    assert "/collect" in paths
    assert "/collect/tasks/{task_id}" in paths
    assert "/api/tasks/start" in paths
    assert "/api/tasks/{task_id}" in paths


def test_collect_page_tabs_and_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        recorded = task_manager.record_completed(
            "collect_github",
            trigger="manual",
            result={
                "status": "SUCCESS",
                "items_found": 1,
                "items_created": 1,
                "items_updated": 0,
                "items_skipped": 0,
                "duration_ms": 900,
                "source_stats": [
                    {
                        "name": "q1",
                        "status": "success",
                        "items_created": 1,
                        "items_updated": 0,
                        "items_skipped": 0,
                        "items_found": 1,
                        "duration_ms": 800,
                    }
                ],
            },
        )
        client = TestClient(create_app())
        resp = client.get("/collect")
        assert resp.status_code == 200
        assert "采集" in resp.text
        assert "手动采集" in resp.text
        assert "定时采集" in resp.text
        assert "采集新闻" in resp.text
        assert "生成日报" not in resp.text
        assert "股票 enrichment" not in resp.text
        assert "/collect/tasks/" in resp.text

        sched = client.get("/collect?tab=scheduled")
        assert sched.status_code == 200
        assert "定时任务记录" in sched.text

        detail = client.get(f"/collect/tasks/{recorded.id}")
        assert detail.status_code == 200
        assert "数据源明细" in detail.text
        assert "q1" in detail.text
        assert "新建" in detail.text
    finally:
        get_settings.cache_clear()


def test_source_stat_helper() -> None:
    from bagel.jobs.metrics import source_stat

    row = source_stat("x", status="failed", error="boom", duration_ms=5)
    assert row["name"] == "x"
    assert row["status"] == "failed"
    assert row["error"] == "boom"
