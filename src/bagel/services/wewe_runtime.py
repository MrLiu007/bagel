"""Start / supervise WeWe-RSS sidecar for local ``bagel dev``.

Design:
- **Docker-first** (image ``cooderl/wewe-rss-sqlite``) — zero Node build for users
- **Local fallback** from ``third_party/wewe-rss`` when Docker is unavailable
  and Node ≥ 20 + pnpm are present
- Started once from ``bagel dev`` (before uvicorn), not from reload workers
- Empty ``WEWE_RSS_BASE_URL`` → effective ``http://127.0.0.1:{port}``
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CONTAINER_NAME = "bagel-wewe-rss"
DEFAULT_IMAGE = "cooderl/wewe-rss-sqlite:latest"
DEFAULT_AUTH = "bagel-wewe"
STATE_NAME = "wewe_rss_runtime.json"


def _settings():
    from bagel.settings import get_settings

    return get_settings()


def data_dir() -> Path:
    s = _settings()
    root = Path(s.data_dir)
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def wewe_data_dir() -> Path:
    path = data_dir() / "wewe-rss"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path() -> Path:
    return data_dir() / STATE_NAME


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_state(data: dict[str, Any]) -> None:
    path = state_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def auth_code(settings=None) -> str:
    s = settings or _settings()
    return (getattr(s, "wewe_rss_auth_code", None) or "").strip() or DEFAULT_AUTH


def listen_port(settings=None) -> int:
    s = settings or _settings()
    try:
        return max(1, min(65535, int(getattr(s, "wewe_rss_port", 4000) or 4000)))
    except (TypeError, ValueError):
        return 4000


def docker_image(settings=None) -> str:
    s = settings or _settings()
    return (
        (getattr(s, "wewe_rss_docker_image", None) or "").strip() or DEFAULT_IMAGE
    )


def effective_wewe_base_url(settings=None) -> str:
    """Configured URL, or auto sidecar URL when empty."""
    s = settings or _settings()
    configured = (getattr(s, "wewe_rss_base_url", None) or "").strip().rstrip("/")
    if configured:
        return configured
    st = load_state()
    if st.get("base_url"):
        return str(st["base_url"]).rstrip("/")
    if st.get("running"):
        return f"http://127.0.0.1:{listen_port(s)}"
    # Optimistic default when auto-start enabled (client may probe)
    if getattr(s, "wewe_rss_active", False) and getattr(s, "wewe_rss_auto_start", True):
        return f"http://127.0.0.1:{listen_port(s)}"
    return ""


def _run_cmd(
    args: list[str],
    *,
    timeout: float = 120.0,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run subprocess with UTF-8 decode (Windows default GBK breaks Docker/Node output)."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
    )


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        proc = _run_cmd(["docker", "info"], timeout=8)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _docker(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return _run_cmd(["docker", *args], timeout=timeout)


def _container_state() -> str:
    """running | exited | missing | unknown"""
    try:
        proc = _docker(
            "inspect",
            "-f",
            "{{.State.Status}}",
            CONTAINER_NAME,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode != 0:
        return "missing"
    return (proc.stdout or "").strip() or "unknown"


def probe_feeds(base_url: str, *, timeout: float = 3.0) -> bool:
    url = f"{base_url.rstrip('/')}/feeds"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            return resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def wait_until_ready(base_url: str, *, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe_feeds(base_url, timeout=2.0):
            return True
        time.sleep(1.0)
    return False


def _docker_image_present(image: str) -> bool:
    try:
        proc = _docker("image", "inspect", image, timeout=15)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _start_docker(settings) -> dict[str, Any]:
    port = listen_port(settings)
    image = docker_image(settings)
    code = auth_code(settings)
    volume = str(wewe_data_dir())
    base = f"http://127.0.0.1:{port}"
    state = _container_state()

    if state == "running":
        # Container already owns the port — do not fall into local pnpm builds.
        ready = wait_until_ready(base, timeout=6.0)
        save_state(
            {
                "mode": "docker",
                "running": ready,
                "base_url": base,
                "container": CONTAINER_NAME,
                "image": image,
            }
        )
        out = {
            "action": "exists",
            "mode": "docker",
            "base_url": base,
            "ready": ready,
            "port_held": True,
        }
        if not ready:
            out["error"] = (
                "docker 容器已在跑但 /feeds 未就绪（请 docker logs bagel-wewe-rss；"
                "勿再开 local，端口已被占用）"
            )
        return out

    if state == "exited":
        proc = _docker("start", CONTAINER_NAME, timeout=60)
        if proc.returncode != 0:
            _docker("rm", "-f", CONTAINER_NAME, timeout=30)
            state = "missing"
        else:
            ready = wait_until_ready(base, timeout=15.0)
            save_state(
                {
                    "mode": "docker",
                    "running": ready,
                    "base_url": base,
                    "container": CONTAINER_NAME,
                    "image": image,
                }
            )
            return {
                "action": "started",
                "mode": "docker",
                "base_url": base,
                "ready": ready,
                "port_held": True,
            }

    if not _docker_image_present(image):
        logger.info("wewe.docker_pull image=%s", image)
        try:
            pull = _docker("pull", image, timeout=120)
        except subprocess.TimeoutExpired:
            return {
                "action": "failed",
                "mode": "docker",
                "error": f"docker pull 超时（{image}）。可手动 docker pull 后重试，或设 WEWE_RSS_RUNTIME=local",
            }
        if pull.returncode != 0:
            err = (pull.stderr or pull.stdout or "")[:220]
            short = err
            if "docker.io" in err.lower() or "auth.docker.io" in err.lower():
                short = (
                    "Docker Hub 不可达/鉴权失败（可换镜像加速或手动 "
                    f"docker pull {image}）"
                )
            return {
                "action": "failed",
                "mode": "docker",
                "error": short,
            }

    run = _docker(
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
        "--restart",
        "unless-stopped",
        "-p",
        f"{port}:4000",
        "-e",
        "DATABASE_TYPE=sqlite",
        "-e",
        f"AUTH_CODE={code}",
        "-e",
        f"SERVER_ORIGIN_URL={base}",
        "-v",
        f"{volume}:/app/data",
        image,
        timeout=120,
    )
    if run.returncode != 0:
        err = (run.stderr or run.stdout or "")[:300]
        return {"action": "failed", "mode": "docker", "error": err}

    ready = wait_until_ready(base, timeout=20.0)
    save_state(
        {
            "mode": "docker",
            "running": ready,
            "base_url": base,
            "container": CONTAINER_NAME,
            "image": image,
        }
    )
    return {
        "action": "started",
        "mode": "docker",
        "base_url": base,
        "ready": ready,
        "container": CONTAINER_NAME,
        "port_held": True,
    }


def _node_major() -> int | None:
    if not shutil.which("node"):
        return None
    try:
        proc = _run_cmd(["node", "-v"], timeout=5)
        text = (proc.stdout or "").strip().lstrip("v")
        return int(text.split(".", 1)[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _pnpm_bin() -> str | None:
    return shutil.which("pnpm")


def _checkout_path(settings) -> Path:
    raw = (settings.wewe_rss_path or "").strip() or "./third_party/wewe-rss"
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    return target


def build_local_checkout(settings=None) -> dict[str, Any]:
    """Run pnpm install + build:server once (explicit; not on bagel dev path)."""
    from bagel.services.wewe_setup import is_checkout_ready

    s = settings or _settings()
    major = _node_major()
    pnpm = _pnpm_bin()
    if major is None or major < 20:
        return {"action": "failed", "error": "需要 Node ≥ 20"}
    if not pnpm:
        return {"action": "failed", "error": "未找到 pnpm"}
    target = _checkout_path(s)
    if not is_checkout_ready(target):
        return {"action": "failed", "error": f"checkout 未就绪: {target}"}
    marker = target / ".bagel_built"
    if marker.is_file():
        return {"action": "exists", "path": str(target)}
    logger.info("wewe.local_build path=%s", target)
    for cmd in ([pnpm, "install"], [pnpm, "run", "build:server"]):
        try:
            proc = _run_cmd(cmd, cwd=str(target), timeout=900)
        except subprocess.TimeoutExpired:
            return {"action": "failed", "error": f"超时: {' '.join(cmd)}"}
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:300]
            return {"action": "failed", "error": err}
    marker.write_text("ok\n", encoding="utf-8")
    return {"action": "built", "path": str(target)}


def _start_local(settings) -> dict[str, Any]:
    """Best-effort local Node start from third_party checkout."""
    from bagel.services.wewe_setup import is_checkout_ready

    major = _node_major()
    pnpm = _pnpm_bin()
    if major is None or major < 20:
        return {
            "action": "skipped",
            "mode": "local",
            "error": "需要 Node ≥ 20（当前无 Docker 镜像时需本机 Node；或修好 Docker Hub 后重试）",
        }
    if not pnpm:
        return {
            "action": "skipped",
            "mode": "local",
            "error": "未找到 pnpm（npm i -g pnpm；或修好 Docker Hub 后用镜像）",
        }

    target = _checkout_path(settings)
    if not is_checkout_ready(target):
        return {
            "action": "skipped",
            "mode": "local",
            "error": f"checkout 未就绪: {target}",
        }

    port = listen_port(settings)
    base = f"http://127.0.0.1:{port}"
    if probe_feeds(base, timeout=2.0):
        save_state({"mode": "local", "running": True, "base_url": base})
        return {"action": "exists", "mode": "local", "base_url": base, "ready": True}

    # Persist minimal server env for sqlite under Bagel data dir
    db_file = wewe_data_dir() / "wewe-rss.db"
    server_env = target / "apps" / "server" / ".env"
    env_text = (
        f"DATABASE_TYPE=sqlite\n"
        f"DATABASE_URL=file:{db_file.as_posix()}\n"
        f"AUTH_CODE={auth_code(settings)}\n"
        f"SERVER_ORIGIN_URL={base}\n"
        f"PORT={port}\n"
    )
    try:
        server_env.parent.mkdir(parents=True, exist_ok=True)
        if not server_env.is_file():
            server_env.write_text(env_text, encoding="utf-8")
    except OSError as exc:
        return {"action": "failed", "mode": "local", "error": str(exc)[:200]}

    log_path = data_dir() / "wewe_rss_local.log"
    # Never run multi-minute pnpm install on bagel dev critical path.
    # Prebuild via: uv run bagel setup-wewe  (or WEWE_RSS_RUNTIME=local after marker exists).
    marker = target / ".bagel_built"
    if not marker.is_file():
        return {
            "action": "skipped",
            "mode": "local",
            "ready": False,
            "error": (
                "本地 WeWe 尚未构建（避免拖慢主站启动）。"
                "请先: uv run bagel setup-wewe --build；或修好 Docker 镜像后重试"
            ),
        }

    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 — kept for process lifetime
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0x00000008
        )
    try:
        proc = subprocess.Popen(
            [pnpm, "run", "start:server"],
            cwd=str(target),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(os.name != "nt"),
        )
    except OSError as exc:
        log_f.close()
        return {"action": "failed", "mode": "local", "error": str(exc)[:200]}

    ready = wait_until_ready(base, timeout=60.0)
    save_state(
        {
            "mode": "local",
            "running": ready,
            "base_url": base,
            "pid": proc.pid,
            "log": str(log_path),
        }
    )
    return {
        "action": "started",
        "mode": "local",
        "base_url": base,
        "ready": ready,
        "pid": proc.pid,
        "log": str(log_path),
    }


def ensure_wewe_rss_running(*, settings=None, start: bool = True) -> dict[str, Any]:
    """Ensure WeWe-RSS is reachable. Used by ``bagel dev`` (start=True).

    Never raises. Prefer Docker; fall back to local Node checkout.
    """
    s = settings or _settings()
    if not getattr(s, "wewe_rss_active", False):
        return {"action": "skipped", "error": "disabled"}
    if not start or not bool(getattr(s, "wewe_rss_auto_start", True)):
        base = effective_wewe_base_url(s)
        ready = bool(base) and probe_feeds(base)
        return {"action": "probe", "base_url": base, "ready": ready}

    runtime = (getattr(s, "wewe_rss_runtime", None) or "auto").strip().lower()
    port = listen_port(s)
    base = f"http://127.0.0.1:{port}"

    # Already up (any previous start)
    if probe_feeds(base, timeout=2.0):
        save_state({"mode": load_state().get("mode") or "external", "running": True, "base_url": base})
        return {"action": "exists", "mode": "external", "base_url": base, "ready": True}

    errors: list[str] = []
    docker_holds_port = False

    if runtime in {"auto", "docker"}:
        if docker_available():
            info = _start_docker(s)
            if info.get("ready"):
                return info
            if info.get("action") in {"exists", "started"} and not info.get("ready"):
                errors.append(str(info.get("error") or "docker 已启动但 /feeds 未就绪"))
                # Container (or just-started instance) still owns :port — local Node would fight it.
                docker_holds_port = True
            else:
                errors.append(str(info.get("error") or "docker 启动失败"))
            if runtime == "docker" or docker_holds_port:
                return {
                    **info,
                    "error": "; ".join(errors)[:300],
                    "ready": False,
                    "hint": (
                        "主站仍可启动。公众号：检查 docker logs bagel-wewe-rss，"
                        "或 docker rm -f bagel-wewe-rss 后修好镜像再开；"
                        "也可 WEWE_RSS_AUTO_START=false"
                    ),
                }
            logger.info("wewe.docker_fallback_local reason=%s", errors[-1][:120])
        elif runtime == "docker":
            return {
                "action": "failed",
                "mode": "docker",
                "error": "未检测到 Docker。请安装 Docker Desktop，或设 WEWE_RSS_RUNTIME=local",
            }

    if runtime in {"auto", "local"}:
        info = _start_local(s)
        if info.get("ready"):
            return info
        errors.append(str(info.get("error") or info.get("action") or "local failed"))
        return {
            "action": info.get("action") or "failed",
            "mode": info.get("mode") or "local",
            "error": "; ".join(errors)[:400],
            "base_url": base,
            "ready": False,
            "hint": (
                "主站仍可启动。公众号功能：修好 Docker Hub 后重开 bagel dev，"
                "或 uv run bagel setup-wewe；也可 WEWE_RSS_AUTO_START=false 稍后再配"
            ),
        }

    return {"action": "skipped", "error": f"unknown runtime={runtime}"}


def stop_wewe_rss_sidecar(*, settings=None) -> dict[str, Any]:
    """Optional stop (not called by default on bagel exit)."""
    del settings
    st = load_state()
    mode = st.get("mode")
    if mode == "docker" and docker_available():
        _docker("stop", CONTAINER_NAME, timeout=60)
        save_state({**st, "running": False})
        return {"action": "stopped", "mode": "docker"}
    pid = st.get("pid")
    if mode == "local" and pid:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            else:
                os.kill(int(pid), 15)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        save_state({**st, "running": False})
        return {"action": "stopped", "mode": "local", "pid": pid}
    return {"action": "noop"}
