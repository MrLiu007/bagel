"""Clone MediaCrawler locally and install Bagel's entry shim (not vendored)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_REPO = "https://github.com/NanmiCoder/MediaCrawler.git"


def project_root() -> Path:
    from bagel.pipeline.paths import project_root as _root

    return _root()


def default_target() -> Path:
    return project_root() / "third_party" / "MediaCrawler"


def patch_entry_src() -> Path:
    return project_root() / "third_party" / "patches" / "bagel_entry.py"


def install_entry_shim(target: Path) -> Path:
    src = patch_entry_src()
    if not src.is_file():
        raise FileNotFoundError(f"missing patch: {src}")
    dest = target / "bagel_entry.py"
    shutil.copy2(src, dest)
    # Keep legacy name for older checkouts / docs
    legacy = target / "intel_center_entry.py"
    if not legacy.is_file():
        shutil.copy2(src, legacy)
    return dest


def setup_mediacrawler(
    *,
    target: Path | None = None,
    repo: str = DEFAULT_REPO,
    ref: str = "main",
    force: bool = False,
) -> dict[str, str]:
    """Clone (or refresh) MediaCrawler and copy bagel_entry.py into it."""
    target = target or default_target()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and any(target.iterdir()) and not (target / ".git").exists():
        # Non-empty without git — refuse unless force (would wipe user data/browser_data)
        if force:
            shutil.rmtree(target)
        else:
            raise FileExistsError(
                f"{target} 已存在且不是 git 仓库。删除后重试，或指定空目录。"
            )

    if (target / ".git").exists():
        subprocess.run(
            ["git", "-C", str(target), "fetch", "--depth", "1", "origin", ref],
            check=False,
            capture_output=True,
            text=True,
        )
        # Best-effort checkout; ignore failure if offline
        subprocess.run(
            ["git", "-C", str(target), "checkout", "-f", f"origin/{ref}"],
            check=False,
            capture_output=True,
            text=True,
        )
        action = "updated"
    elif target.exists() and force:
        shutil.rmtree(target)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        action = "cloned"
    else:
        # try branch first; fall back without --branch if tag/default differs
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo, str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo, str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
        action = "cloned"

    entry = install_entry_shim(target)
    return {
        "action": action,
        "path": str(target),
        "entry": str(entry),
        "repo": repo,
        "ref": ref,
    }
