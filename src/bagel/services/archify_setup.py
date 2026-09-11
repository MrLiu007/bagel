"""Clone Archify locally (gitignored); Bagel only shells out to Node CLI."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REPO = "https://github.com/tt-a1i/archify.git"
DEFAULT_REF = "main"
VPN_HINT = (
    "Archify 托管在 GitHub。若 clone 失败请开启 VPN / 代理，"
    "或设置 ARCHIFY_GIT_URL 镜像后重启 bagel dev（ARCHIFY_AUTO_SETUP=true 时自动安装）。"
)


def project_root() -> Path:
    from bagel.pipeline.paths import project_root as _root

    return _root()


def default_target() -> Path:
    return project_root() / "third_party" / "archify"


def resolve_repo_url(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from bagel.settings import get_settings

        url = (get_settings().archify_git_url or "").strip()
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

        ref = (get_settings().archify_git_ref or "").strip()
        if ref:
            return ref
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_REF


def package_root(target: Path | None = None) -> Path:
    """Inner npm package directory containing bin/archify.mjs."""
    root = target or default_target()
    inner = root / "archify"
    if (inner / "bin" / "archify.mjs").is_file():
        return inner
    if (root / "bin" / "archify.mjs").is_file():
        return root
    return inner


def is_checkout_ready(target: Path | None = None) -> bool:
    root = target or default_target()
    return (package_root(root) / "bin" / "archify.mjs").is_file()


def node_bin() -> str | None:
    return shutil.which("node")


def is_node_ready() -> bool:
    return bool(node_bin())


def setup_archify(
    *,
    target: Path | None = None,
    repo: str | None = None,
    ref: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    target = target or default_target()
    repo = resolve_repo_url(repo)
    ref = resolve_ref(ref)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and any(target.iterdir()) and not (target / ".git").exists():
        if force:
            shutil.rmtree(target)
        else:
            raise FileExistsError(f"{target} 已存在且不是 git 仓库。{VPN_HINT}")

    if (target / ".git").exists():
        subprocess.run(
            ["git", "-C", str(target), "fetch", "--depth", "1", "origin", ref],
            check=False,
            capture_output=True,
            text=True,
        )
        for cand in (ref, f"origin/{ref}", "FETCH_HEAD"):
            proc = subprocess.run(
                ["git", "-C", str(target), "checkout", "-f", cand],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                break
        action = "updated"
    else:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo, str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            proc2 = subprocess.run(
                ["git", "clone", "--depth", "1", repo, str(target)],
                capture_output=True,
                text=True,
            )
            if proc2.returncode != 0:
                raise RuntimeError(
                    f"git clone archify 失败。{VPN_HINT} detail={(proc.stderr or '')[:300]}"
                )
        action = "cloned"

    if not is_checkout_ready(target):
        raise RuntimeError(f"Archify 目录异常（缺少 bin/archify.mjs）：{target}。{VPN_HINT}")

    return {
        "action": action,
        "path": str(target),
        "package": str(package_root(target)),
        "repo": repo,
        "ref": ref,
        "node": node_bin() or "MISSING",
    }


def ensure_archify_on_startup(*, settings=None) -> dict[str, str] | None:
    from bagel.settings import get_settings

    settings = settings or get_settings()
    if not settings.enable_archify or not settings.archify_auto_setup:
        return None
    raw = (settings.archify_path or "").strip() or "./third_party/archify"
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    if is_checkout_ready(target):
        return {"action": "exists", "path": str(target)}
    if not is_node_ready():
        logger.warning("archify.skip_auto_setup reason=node_missing")
        return {"action": "skipped", "error": "未找到 node（Archify 需要 Node >= 18）"}
    try:
        info = setup_archify(target=target)
        logger.info("archify.%s path=%s", info["action"], info["path"])
        return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("archify.auto_setup_failed err=%s | %s", exc, VPN_HINT)
        return {"action": "failed", "error": str(exc)[:300]}
