"""User isolation for collect tasks and per-user config overlays."""

from __future__ import annotations

from bagel.services.tasks import TaskManager
from bagel.services import user_config as user_cfg


def test_task_list_isolated_by_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from bagel.settings import get_settings

    get_settings.cache_clear()
    mgr = TaskManager()
    a = mgr.record_completed(
        "collect_news",
        trigger="manual",
        result={"status": "SUCCESS", "items_created": 1, "items_found": 1, "duration_ms": 10},
    )
    # record_completed doesn't set owner — simulate two manual owners via start path fields
    a.owner_id = "user-a"
    mgr._tasks[a.id].owner_id = "user-a"
    b = mgr.record_completed(
        "collect_education",
        trigger="manual",
        result={"status": "SUCCESS", "items_created": 2, "items_found": 2, "duration_ms": 20},
    )
    mgr._tasks[b.id].owner_id = "user-b"
    sched = mgr.record_completed(
        "collect_news",
        trigger="scheduled",
        result={"status": "SUCCESS", "items_created": 3, "items_found": 3, "duration_ms": 30},
    )
    assert sched.owner_id is None

    for_a = mgr.list_recent(20, owner_id="user-a")
    ids_a = {t.id for t in for_a}
    assert a.id in ids_a
    assert b.id not in ids_a
    assert sched.id in ids_a  # shared scheduled

    for_b = mgr.list_recent(20, trigger="manual", owner_id="user-b")
    assert {t.id for t in for_b} == {b.id}
    get_settings.cache_clear()


def test_user_config_overlay(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from bagel.settings import get_settings

    get_settings.cache_clear()
    uid = "11111111-1111-1111-1111-111111111111"
    path = user_cfg.save_user_overrides(uid, {"LLM_MODEL": "my-model", "COLLECT_LOOKBACK_DAYS": "7"})
    assert path.exists()
    merged = user_cfg.merged_config_for_user(uid)
    assert merged["LLM_MODEL"] == "my-model"
    assert merged["COLLECT_LOOKBACK_DAYS"] == "7"
    # Other user sees defaults (no override)
    other = user_cfg.merged_config_for_user("22222222-2222-2222-2222-222222222222")
    assert other.get("LLM_MODEL") != "my-model" or other.get("LLM_MODEL") == get_settings().llm_model
    catalog = user_cfg.catalog_for_ui(uid, is_admin=False)
    flat = [f for g in catalog for f in g["fields"]]
    llm = next(f for f in flat if f["key"] == "LLM_MODEL")
    assert llm["source"] == "user"
    port = next(f for f in flat if f["key"] == "APP_PORT")
    assert port["readonly"] is True
    get_settings.cache_clear()
