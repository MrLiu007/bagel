"""Manual task runner + progress API."""

from __future__ import annotations

import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.services.tasks import TaskManager


def test_task_manager_progress_and_success() -> None:
    mgr = TaskManager()

    def fake_news(session, on_progress=None, cn_only=False, settings=None):
        if on_progress:
            on_progress(current=0, total=2, message="start")
            on_progress(current=1, total=2, message="mid")
            on_progress(current=2, total=2, message="done")
        return {"items_found": 2, "items_created": 1, "status": "SUCCESS"}

    with patch("bagel.jobs.news.run_collect_news", side_effect=fake_news), patch(
        "bagel.services.tasks.get_engine"
    ), patch("bagel.services.tasks.get_session_factory") as factory:
        session = factory.return_value.return_value
        session.commit = lambda: None
        session.rollback = lambda: None
        session.close = lambda: None
        state = mgr.start("collect_news", options={"cn_only": True})
        # wait for background thread
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
        assert done.result["items_created"] == 1


def test_collect_routes_registered() -> None:
    paths = set(create_app().openapi()["paths"].keys())
    assert "/collect" in paths
    assert "/api/tasks/start" in paths
    assert "/api/tasks/{task_id}" in paths


def test_collect_page_renders() -> None:
    client = TestClient(create_app())
    resp = client.get("/collect")
    assert resp.status_code == 200
    assert "手动采集" in resp.text
    assert "进度" in resp.text or "progress" in resp.text.lower() or "bar" in resp.text
