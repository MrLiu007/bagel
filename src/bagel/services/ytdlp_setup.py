"""Clone yt-dlp locally and install into its own venv (not vendored)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REPO = "https://github.com/yt-dlp/yt-dlp.git"
# Keep in sync with settings.ytdlp_git_ref / .env.example — B 站 412 等需较新 extractor。
DEFAULT_REF = "2026.08.19"
VPN_HINT = (
    "yt-dlp 托管在 GitHub。若 clone/fetch 超时或失败，请开启 VPN（或 HTTP(S)_PROXY），"
    "或在 .env 设置 YTDLP_GIT_URL 为可用镜像后再启动 / 执行 bagel setup-ytdlp。"
)


def project_root() -> Path:
    from bagel.pipeline.paths import project_root as _root

    return _root()


def default_target() -> Path:
    return project_root() / "third_party" / "yt-dlp"


def resolve_repo_url(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from bagel.settings import get_settings

        url = (get_settings().ytdlp_git_url or "").strip()
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

        ref = (get_settings().ytdlp_git_ref or "").strip()
        if ref:
            return ref
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_REF


def is_checkout_ready(target: Path | None = None) -> bool:
    """True when yt-dlp source tree exists."""
    root = target or default_target()
    return (root / "yt_dlp" / "__init__.py").is_file() or (root / "yt_dlp" / "__main__.py").is_file()


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def venv_ytdlp(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "yt-dlp.exe"
    return root / ".venv" / "bin" / "yt-dlp"


def is_venv_ready(target: Path | None = None) -> bool:
    """True when the checkout venv can actually run yt-dlp."""
    root = target or default_target()
    if venv_ytdlp(root).is_file():
        return True
    py = venv_python(root)
    if not py.is_file():
        return False
    try:
        proc = subprocess.run(
            [str(py), "-c", "import yt_dlp"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def checkout_ref(target: Path | None = None) -> str | None:
    """Best-effort git describe / HEAD short for status UI."""
    root = target or default_target()
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def install_venv(target: Path | None = None) -> dict[str, str]:
    """Create .venv in checkout and pip install -e ."""
    root = target or default_target()
    if not is_checkout_ready(root):
        raise RuntimeError(f"yt-dlp 源码未就绪：{root}。请先 bagel setup-ytdlp。{VPN_HINT}")

    py = venv_python(root)
    if not py.is_file():
        subprocess.run(
            [sys.executable, "-m", "venv", str(root / ".venv")],
            check=True,
            cwd=str(root),
        )

    pip_cmd = [str(py), "-m", "pip"]
    # Self-upgrade of pip can fail on Windows ("To modify pip…"); ignore and continue.
    subprocess.run(
        [*pip_cmd, "install", "-U", "pip", "wheel"],
        check=False,
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [*pip_cmd, "install", "-e", "."],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"yt-dlp venv 安装失败：{(proc.stderr or proc.stdout or '')[:400]}"
        )
    return {"action": "venv_installed", "path": str(root), "python": str(py)}


def setup_ytdlp(
    *,
    target: Path | None = None,
    repo: str | None = None,
    ref: str | None = None,
    force: bool = False,
    install_deps: bool = True,
) -> dict[str, str]:
    """Clone (or refresh) yt-dlp and optionally install its venv."""
    target = target or default_target()
    repo = resolve_repo_url(repo)
    ref = resolve_ref(ref)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and any(target.iterdir()) and not (target / ".git").exists():
        if force:
            shutil.rmtree(target)
        else:
            raise FileExistsError(
                f"{target} 已存在且不是 git 仓库。删除后重试，或指定空目录。{VPN_HINT}"
            )

    if (target / ".git").exists():
        _fetch_and_checkout(target, ref)
        action = "updated"
    elif target.exists() and force:
        shutil.rmtree(target)
        _clone(repo, ref, target)
        action = "cloned"
    else:
        try:
            _clone(repo, ref, target)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"git clone yt-dlp 失败（repo={repo}）。{VPN_HINT} detail={exc.stderr or exc}"
            ) from exc
        action = "cloned"

    if not is_checkout_ready(target):
        raise RuntimeError(f"yt-dlp 目录异常（缺少 yt_dlp 包）：{target}。{VPN_HINT}")

    info: dict[str, str] = {
        "action": action,
        "path": str(target),
        "repo": repo,
        "ref": ref,
    }
    # Always reinstall editable package on setup so tag bumps take effect.
    if install_deps:
        vinfo = install_venv(target)
        info["venv"] = vinfo.get("action", "venv_installed")
    elif is_venv_ready(target):
        info["venv"] = "exists"
    else:
        info["venv"] = "missing"
    return info


def ensure_ytdlp_on_startup(*, settings=None) -> dict[str, str] | None:
    """If AV is enabled and checkout missing, clone once. Never raises."""
    from bagel.settings import get_settings

    settings = settings or get_settings()
    if not settings.ytdlp_active:
        return None
    if not bool(getattr(settings, "ytdlp_auto_setup", True)):
        logger.info("ytdlp.auto_setup=disabled")
        return None

    raw = (settings.ytdlp_path or "").strip() or "./third_party/yt-dlp"
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if is_checkout_ready(target):
        if not is_venv_ready(target):
            try:
                install_venv(target)
                logger.info("ytdlp.venv_installed path=%s", target)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ytdlp.venv_install_failed err=%s", exc)
        return {"action": "exists", "path": str(target)}

    logger.info("ytdlp.missing path=%s — cloning on startup (GitHub may need VPN)…", target)
    try:
        info = setup_ytdlp(
            target=target,
            repo=resolve_repo_url(None),
            ref=resolve_ref(None),
            install_deps=True,
        )
        logger.info("ytdlp.%s path=%s", info["action"], info["path"])
        return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("ytdlp.auto_setup_failed err=%s | %s", exc, VPN_HINT)
        return {"action": "failed", "error": str(exc)[:300]}


def _fetch_and_checkout(target: Path, ref: str) -> None:
    """Fetch a branch or tag and hard-checkout (tags are not origin/{ref})."""
    # Already on the desired tag/commit — skip network (helps when GitHub is flaky).
    current = checkout_ref(target)
    if current and (current == ref or current.startswith(f"{ref}-") or ref in current):
        return

    fetch = subprocess.run(
        ["git", "-C", str(target), "fetch", "--depth", "1", "origin", "tag", ref, "--force"],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        fetch = subprocess.run(
            ["git", "-C", str(target), "fetch", "--depth", "1", "origin", ref],
            capture_output=True,
            text=True,
        )
    if fetch.returncode != 0:
        # Keep existing tree if we already have the package; reinstall can still proceed.
        if is_checkout_ready(target) and current:
            logger.warning(
                "ytdlp.fetch_skipped keep=%s wanted=%s err=%s",
                current,
                ref,
                (fetch.stderr or "")[:200],
            )
            return
        raise RuntimeError(
            f"git fetch yt-dlp 失败（ref={ref}）。{VPN_HINT} detail={(fetch.stderr or '')[:300]}"
        )

    for candidate in (ref, f"tags/{ref}", "FETCH_HEAD", f"origin/{ref}"):
        checkout = subprocess.run(
            ["git", "-C", str(target), "checkout", "-f", candidate],
            capture_output=True,
            text=True,
        )
        if checkout.returncode == 0:
            return
    raise RuntimeError(
        f"git checkout yt-dlp 失败（ref={ref}）。{VPN_HINT} detail={(checkout.stderr or '')[:300]}"
    )


def _clone(repo: str, ref: str, target: Path) -> None:
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, repo, str(target)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return
    proc2 = subprocess.run(
        ["git", "clone", "--depth", "1", repo, str(target)],
        capture_output=True,
        text=True,
    )
    if proc2.returncode != 0:
        raise subprocess.CalledProcessError(
            proc2.returncode,
            proc2.args,
            output=proc2.stdout,
            stderr=(proc.stderr or "") + "\n" + (proc2.stderr or ""),
        )
    # Shallow clone default branch, then try to fetch the requested ref.
    try:
        _fetch_and_checkout(target, ref)
    except RuntimeError:
        pass
