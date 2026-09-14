"""Clone WeWe-RSS into third_party/ (gitignored) — source not vendored.

Runtime start (Docker / local Node) lives in ``wewe_runtime.py``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REPO = "https://github.com/cooderl/wewe-rss.git"
VPN_HINT = (
    "WeWe-RSS 托管在 GitHub。若 clone 失败，请开启 VPN / HTTP(S)_PROXY，"
    "或设置 WEWE_RSS_GIT_URL 为镜像后再执行 bagel setup-wewe。"
)


def project_root() -> Path:
    from bagel.pipeline.paths import project_root as _root

    return _root()


def default_target() -> Path:
    return project_root() / "third_party" / "wewe-rss"


def resolve_repo_url(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from bagel.settings import get_settings

        url = (get_settings().wewe_rss_git_url or "").strip()
        if url:
            return url
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_REPO


def resolve_ref(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from bagel.settings import get_settings

        ref = (get_settings().wewe_rss_git_ref or "").strip()
        if ref:
            return ref
    except Exception:  # noqa: BLE001
        pass
    return "main"


def is_checkout_ready(target: Path | None = None) -> bool:
    root = target or default_target()
    return (root / "package.json").is_file() and (root / "apps" / "server").is_dir()


def setup_wewe_rss(
    *,
    target: Path | None = None,
    repo: str | None = None,
    ref: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    """Clone WeWe-RSS when missing. Returns action metadata."""
    dest = target or default_target()
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = resolve_repo_url(repo)
    branch = resolve_ref(ref)

    if dest.exists() and not (dest / ".git").is_dir():
        if force:
            shutil.rmtree(dest)
        else:
            raise FileExistsError(
                f"{dest} exists but is not a git checkout. "
                "Remove it or pass force=True / bagel setup-wewe --force"
            )

    if is_checkout_ready(dest) and (dest / ".git").is_dir():
        return {"action": "exists", "path": str(dest), "repo": url, "ref": branch}

    if (dest / ".git").is_dir() and not is_checkout_ready(dest):
        # Incomplete clone — remove and redo
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        branch,
        url,
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Some hosts reject --branch on shallow; retry plain
        cmd2 = ["git", "clone", "--depth", "1", url, str(dest)]
        proc2 = subprocess.run(cmd2, capture_output=True, text=True)
        if proc2.returncode != 0:
            err = (proc2.stderr or proc.stderr or "")[:400]
            raise RuntimeError(f"git clone failed: {err}") from None
        # checkout ref if possible
        subprocess.run(
            ["git", "-C", str(dest), "checkout", branch],
            capture_output=True,
            text=True,
        )

    if not is_checkout_ready(dest):
        raise RuntimeError(f"WeWe-RSS checkout incomplete at {dest}")
    return {"action": "cloned", "path": str(dest), "repo": url, "ref": branch}


def ensure_wewe_rss_on_startup(*, settings=None) -> dict[str, str] | None:
    """Clone WeWe-RSS once when enabled. Never raises."""
    from bagel.settings import get_settings

    settings = settings or get_settings()
    if not getattr(settings, "wewe_rss_active", False):
        return None
    if not bool(getattr(settings, "wewe_rss_auto_setup", True)):
        logger.info("wewe.auto_setup=disabled")
        return None

    raw = (settings.wewe_rss_path or "").strip() or "./third_party/wewe-rss"
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if is_checkout_ready(target):
        return {"action": "exists", "path": str(target)}

    logger.info("wewe.missing path=%s — cloning…", target)
    try:
        info = setup_wewe_rss(target=target)
        logger.info("wewe.%s path=%s", info["action"], info["path"])
        return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("wewe.auto_setup_failed err=%s | %s", exc, VPN_HINT)
        return {"action": "failed", "error": str(exc)[:300]}
