"""Clone MediaCrawler locally and install Bagel's entry shim (not vendored)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REPO = "https://github.com/NanmiCoder/MediaCrawler.git"
VPN_HINT = (
    "MediaCrawler 托管在 GitHub。若 clone/fetch 超时或失败，请开启系统/终端 VPN（或 HTTP(S)_PROXY），"
    "或在 .env 设置 MEDIA_CRAWLER_GIT_URL 为可用镜像后再启动 / 执行 bagel setup-media。"
)


def project_root() -> Path:
    from bagel.pipeline.paths import project_root as _root

    return _root()


def default_target() -> Path:
    return project_root() / "third_party" / "MediaCrawler"


def patch_entry_src() -> Path:
    return project_root() / "third_party" / "patches" / "bagel_entry.py"


def resolve_repo_url(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from bagel.settings import get_settings

        url = (get_settings().media_crawler_git_url or "").strip()
        if url:
            return url
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_REPO


def is_checkout_ready(target: Path | None = None) -> bool:
    """True when a usable MediaCrawler tree exists (main.py present)."""
    root = target or default_target()
    return (root / "main.py").is_file()


def install_entry_shim(target: Path) -> Path:
    """Copy bagel_entry.py only when content differs (avoid WatchFiles reload loops)."""
    src = patch_entry_src()
    if not src.is_file():
        raise FileNotFoundError(f"missing patch: {src}")
    # utf-8-sig strips a leading BOM so we never re-poison the MediaCrawler tree.
    src_text = src.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    dest = target / "bagel_entry.py"
    if dest.is_file():
        try:
            if dest.read_text(encoding="utf-8-sig").lstrip("\ufeff") == src_text:
                sanitize_mediacrawler_utf8_bom(target)
                return dest
        except OSError:
            pass
    _write_text_no_bom(dest, src_text)
    legacy = target / "intel_center_entry.py"
    if not legacy.is_file():
        _write_text_no_bom(legacy, src_text)
    sanitize_mediacrawler_utf8_bom(target)
    return dest


_UTF8_BOM = b"\xef\xbb\xbf"


def _write_text_no_bom(path: Path, text: str) -> None:
    """Write UTF-8 without BOM (Windows tools sometimes reintroduce U+FEFF)."""
    data = text.lstrip("\ufeff").encode("utf-8")
    path.write_bytes(data)


def _strip_utf8_bom_file(path: Path) -> bool:
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if not raw.startswith(_UTF8_BOM):
        return False
    try:
        path.write_bytes(raw[len(_UTF8_BOM) :])
    except OSError:
        return False
    return True


def _site_packages_dirs(venv: Path) -> list[Path]:
    out: list[Path] = []
    win = venv / "Lib" / "site-packages"
    if win.is_dir():
        out.append(win)
    lib = venv / "lib"
    if lib.is_dir():
        for py in lib.glob("python*"):
            sp = py / "site-packages"
            if sp.is_dir():
                out.append(sp)
    return out


def sanitize_mediacrawler_utf8_bom(target: Path | None = None) -> int:
    """Strip UTF-8 BOM from MediaCrawler project + venv site-packages ``*.py``.

    Some Windows environments rewrite text files with a leading U+FEFF. That breaks:
    - OpenCV ``compile(config.py)``
    - PyExecJS and other packages declaring ``coding: ascii``
      (``SyntaxError: encoding problem: ascii with BOM``)
    """
    root = target or default_target()
    if not root.is_dir():
        return 0
    fixed = 0
    venv = root / ".venv"
    marker = venv / ".bagel_bom_clean" if venv.is_dir() else None
    probes: list[Path] = []
    if venv.is_dir():
        for sp in _site_packages_dirs(venv):
            probes.extend([sp / "execjs" / "__init__.py", sp / "cv2" / "config.py"])
    probes_dirty = False
    for probe in probes:
        if not probe.is_file():
            continue
        try:
            if probe.read_bytes().startswith(_UTF8_BOM):
                probes_dirty = True
                break
        except OSError:
            probes_dirty = True
            break

    need_full_venv = probes_dirty or not (marker and marker.is_file())
    if need_full_venv and venv.is_dir():
        for sp in _site_packages_dirs(venv):
            for path in sp.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                if _strip_utf8_bom_file(path):
                    fixed += 1
        try:
            if marker is not None:
                _write_text_no_bom(marker, f"fixed={fixed}\n")
        except OSError:
            pass

    for path in root.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if _strip_utf8_bom_file(path):
            fixed += 1

    if fixed:
        logger.info("mediacrawler.bom_stripped files=%s path=%s", fixed, root)
    return fixed


# Back-compat alias used by older call sites / tests.
def sanitize_opencv_utf8_bom(target: Path | None = None) -> int:
    return sanitize_mediacrawler_utf8_bom(target)


def setup_mediacrawler(
    *,
    target: Path | None = None,
    repo: str | None = None,
    ref: str = "main",
    force: bool = False,
) -> dict[str, str]:
    """Clone (or refresh) MediaCrawler and copy bagel_entry.py into it."""
    target = target or default_target()
    repo = resolve_repo_url(repo)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and any(target.iterdir()) and not (target / ".git").exists():
        if force:
            shutil.rmtree(target)
        else:
            raise FileExistsError(
                f"{target} 已存在且不是 git 仓库。删除后重试，或指定空目录。{VPN_HINT}"
            )

    if (target / ".git").exists():
        subprocess.run(
            ["git", "-C", str(target), "fetch", "--depth", "1", "origin", ref],
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(target), "checkout", "-f", f"origin/{ref}"],
            check=False,
            capture_output=True,
            text=True,
        )
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
                f"git clone MediaCrawler 失败（repo={repo}）。{VPN_HINT} detail={exc.stderr or exc}"
            ) from exc
        action = "cloned"

    if not (target / "main.py").is_file():
        raise RuntimeError(f"MediaCrawler 目录异常（缺少 main.py）：{target}。{VPN_HINT}")

    entry = install_entry_shim(target)
    return {
        "action": action,
        "path": str(target),
        "entry": str(entry),
        "repo": repo,
        "ref": ref,
    }


def ensure_mediacrawler_on_startup(*, settings=None) -> dict[str, str] | None:
    """If media is enabled and checkout missing, clone once. Never raises to caller."""
    from bagel.settings import get_settings

    settings = settings or get_settings()
    if not settings.media_active:
        return None
    if not bool(getattr(settings, "media_crawler_auto_setup", True)):
        logger.info("mediacrawler.auto_setup=disabled")
        return None

    raw = (settings.media_crawler_path or "").strip() or "./third_party/MediaCrawler"
    target = Path(raw)
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()

    if is_checkout_ready(target):
        try:
            install_entry_shim(target)
        except OSError as exc:
            logger.warning("mediacrawler.shim_copy_failed err=%s", exc)
        return {"action": "exists", "path": str(target)}

    logger.info(
        "mediacrawler.missing path=%s — cloning on startup (GitHub may need VPN)…",
        target,
    )
    try:
        info = setup_mediacrawler(
            target=target,
            repo=resolve_repo_url(None),
            ref=(getattr(settings, "media_crawler_git_ref", None) or "main").strip() or "main",
        )
        logger.info("mediacrawler.%s path=%s", info["action"], info["path"])
        logger.warning(
            "MediaCrawler 源码已就绪；仍需在其目录创建 .venv 并安装依赖 / Playwright 后才能抓取。"
        )
        return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("mediacrawler.auto_setup_failed err=%s | %s", exc, VPN_HINT)
        return {"action": "failed", "error": str(exc)[:300]}


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
