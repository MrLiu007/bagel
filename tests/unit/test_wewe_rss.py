"""Unit tests for WeWe-RSS setup / runtime helpers (no live Docker required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bagel.services import wewe_runtime, wewe_setup


def test_is_checkout_ready_requires_package_and_server(tmp_path: Path) -> None:
    assert not wewe_setup.is_checkout_ready(tmp_path)
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert not wewe_setup.is_checkout_ready(tmp_path)
    (tmp_path / "apps" / "server").mkdir(parents=True)
    assert wewe_setup.is_checkout_ready(tmp_path)


def test_ensure_wewe_skipped_when_disabled() -> None:
    settings = MagicMock()
    settings.wewe_rss_active = False
    assert wewe_setup.ensure_wewe_rss_on_startup(settings=settings) is None


def test_ensure_wewe_exists_when_checkout_ready(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "apps" / "server").mkdir(parents=True)
    settings = MagicMock()
    settings.wewe_rss_active = True
    settings.wewe_rss_auto_setup = True
    settings.wewe_rss_path = str(tmp_path)
    info = wewe_setup.ensure_wewe_rss_on_startup(settings=settings)
    assert info is not None
    assert info["action"] == "exists"


def test_effective_base_url_uses_configured() -> None:
    settings = MagicMock()
    settings.wewe_rss_base_url = "http://127.0.0.1:4000/"
    settings.wewe_rss_active = True
    settings.wewe_rss_auto_start = True
    settings.wewe_rss_port = 4000
    assert wewe_runtime.effective_wewe_base_url(settings) == "http://127.0.0.1:4000"


def test_ensure_running_skips_when_already_up(monkeypatch) -> None:
    settings = MagicMock()
    settings.wewe_rss_active = True
    settings.wewe_rss_auto_start = True
    settings.wewe_rss_runtime = "auto"
    settings.wewe_rss_port = 4000
    settings.wewe_rss_base_url = ""
    settings.wewe_rss_auth_code = "bagel-wewe"
    settings.data_dir = "data"

    monkeypatch.setattr(wewe_runtime, "probe_feeds", lambda *a, **k: True)
    monkeypatch.setattr(wewe_runtime, "save_state", lambda data: None)
    monkeypatch.setattr(wewe_runtime, "load_state", lambda: {})

    info = wewe_runtime.ensure_wewe_rss_running(settings=settings, start=True)
    assert info["action"] == "exists"
    assert info["ready"] is True


def test_ensure_running_docker_path(monkeypatch, tmp_path: Path) -> None:
    settings = MagicMock()
    settings.wewe_rss_active = True
    settings.wewe_rss_auto_start = True
    settings.wewe_rss_runtime = "docker"
    settings.wewe_rss_port = 4000
    settings.wewe_rss_base_url = ""
    settings.wewe_rss_auth_code = "x"
    settings.wewe_rss_docker_image = "cooderl/wewe-rss-sqlite:latest"
    settings.data_dir = str(tmp_path)

    monkeypatch.setattr(wewe_runtime, "probe_feeds", lambda *a, **k: False)
    monkeypatch.setattr(wewe_runtime, "docker_available", lambda: True)
    monkeypatch.setattr(wewe_runtime, "_container_state", lambda: "missing")
    monkeypatch.setattr(
        wewe_runtime,
        "_docker",
        lambda *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(wewe_runtime, "wait_until_ready", lambda *a, **k: True)
    monkeypatch.setattr(wewe_runtime, "save_state", lambda data: None)

    info = wewe_runtime.ensure_wewe_rss_running(settings=settings, start=True)
    assert info["mode"] == "docker"
    assert info["ready"] is True
    assert "4000" in info["base_url"]


def test_run_cmd_uses_utf8_errors_replace(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(wewe_runtime.subprocess, "run", fake_run)
    wewe_runtime._run_cmd(["docker", "info"], timeout=5)
    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "replace"


def test_ensure_running_skips_local_when_docker_holds_port(monkeypatch, tmp_path: Path) -> None:
    settings = MagicMock()
    settings.wewe_rss_active = True
    settings.wewe_rss_auto_start = True
    settings.wewe_rss_runtime = "auto"
    settings.wewe_rss_port = 4000
    settings.wewe_rss_base_url = ""
    settings.wewe_rss_auth_code = "x"
    settings.wewe_rss_docker_image = "cooderl/wewe-rss-sqlite:latest"
    settings.data_dir = str(tmp_path)

    local_called = {"n": 0}

    def boom_local(*_a, **_k):
        local_called["n"] += 1
        return {"action": "started", "ready": True}

    monkeypatch.setattr(wewe_runtime, "probe_feeds", lambda *a, **k: False)
    monkeypatch.setattr(wewe_runtime, "docker_available", lambda: True)
    monkeypatch.setattr(
        wewe_runtime,
        "_start_docker",
        lambda *_a, **_k: {
            "action": "exists",
            "mode": "docker",
            "ready": False,
            "port_held": True,
            "error": "docker 容器已在跑但 /feeds 未就绪",
            "base_url": "http://127.0.0.1:4000",
        },
    )
    monkeypatch.setattr(wewe_runtime, "_start_local", boom_local)
    monkeypatch.setattr(wewe_runtime, "save_state", lambda data: None)
    monkeypatch.setattr(wewe_runtime, "load_state", lambda: {})

    info = wewe_runtime.ensure_wewe_rss_running(settings=settings, start=True)
    assert info["ready"] is False
    assert local_called["n"] == 0
    assert "主站仍可启动" in (info.get("hint") or "")


def test_start_local_skips_without_build_marker(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "apps" / "server").mkdir(parents=True)
    settings = MagicMock()
    settings.wewe_rss_path = str(tmp_path)
    settings.wewe_rss_port = 4000
    settings.wewe_rss_auth_code = "x"
    settings.data_dir = str(tmp_path / "data")

    monkeypatch.setattr(wewe_runtime, "_node_major", lambda: 22)
    monkeypatch.setattr(wewe_runtime, "_pnpm_bin", lambda: "pnpm")
    monkeypatch.setattr(wewe_runtime, "probe_feeds", lambda *a, **k: False)
    monkeypatch.setattr(wewe_runtime, "_settings", lambda: settings)

    info = wewe_runtime._start_local(settings)
    assert info["action"] == "skipped"
    assert "尚未构建" in info["error"]

    from bagel.integrations.wewe_rss import WeweRssClient

    settings = MagicMock()
    settings.wewe_rss_base_url = ""
    settings.wewe_rss_auth_code = ""
    monkeypatch.setattr(
        "bagel.services.wewe_runtime.effective_wewe_base_url",
        lambda s=None: "http://127.0.0.1:4000",
    )
    client = WeweRssClient(settings)
    assert client.base_url == "http://127.0.0.1:4000"
    assert client.enabled
