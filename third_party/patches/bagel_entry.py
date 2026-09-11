# -*- coding: utf-8 -*-
"""Bagel entry shim for MediaCrawler — force Playwright so QR login is visible.

Copied into a local MediaCrawler checkout by `bagel setup-media`.
We do NOT vendor MediaCrawler source; only this thin wrapper lives in Bagel.

Rich options (comments / media download) default OFF; Bagel injects
BAGEL_MC_GET_* env vars from `.env` before launch.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


_UTF8_BOM = b"\xef\xbb\xbf"


def _strip_utf8_bom_file(path: Path) -> bool:
    """Remove leading UTF-8 BOM from a text file."""
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


def _iter_site_packages(venv: Path) -> list[Path]:
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


def _sanitize_python_bom_tree(root: Path, *, skip_venv: bool = False) -> int:
    """Strip UTF-8 BOM from all .py under root (optional skip of .venv)."""
    if not root.is_dir():
        return 0
    fixed = 0
    for path in root.rglob("*.py"):
        if skip_venv and ".venv" in path.parts:
            continue
        if "__pycache__" in path.parts:
            continue
        if _strip_utf8_bom_file(path):
            fixed += 1
    return fixed


def _sanitize_venv_and_project_bom() -> None:
    """Whole-venv + project BOM scrub.

    A Windows environment may rewrite packages with UTF-8 BOM. That breaks:
    - OpenCV bootstrap compile(config.py)
    - packages declaring ``# -*- coding: ascii -*-`` (e.g. PyExecJS) with
      ``SyntaxError: encoding problem: ascii with BOM``
    """
    root = Path(__file__).resolve().parent
    venv = root / ".venv"
    fixed = 0
    marker = venv / ".bagel_bom_clean" if venv.is_dir() else None
    probes = []
    if venv.is_dir():
        for sp in _iter_site_packages(venv):
            probes.extend(
                [
                    sp / "execjs" / "__init__.py",
                    sp / "cv2" / "config.py",
                ]
            )
    probes_ok = True
    for probe in probes:
        if not probe.is_file():
            continue
        try:
            if probe.read_bytes().startswith(_UTF8_BOM):
                probes_ok = False
                break
        except OSError:
            probes_ok = False
            break
    if probes_ok and marker is not None and marker.is_file():
        # Still scrub project sources lightly — cheap relative to site-packages.
        proj = _sanitize_python_bom_tree(root, skip_venv=True)
        if proj:
            print(f"[Bagel] stripped UTF-8 BOM from {proj} project file(s)", flush=True)
        return

    if venv.is_dir():
        for sp in _iter_site_packages(venv):
            fixed += _sanitize_python_bom_tree(sp, skip_venv=False)
        try:
            if marker is not None:
                marker.write_text(f"fixed={fixed}\n", encoding="utf-8", newline="\n")
        except OSError:
            pass
    fixed += _sanitize_python_bom_tree(root, skip_venv=True)
    if fixed:
        print(f"[Bagel] stripped UTF-8 BOM from {fixed} Python file(s)", flush=True)


# Cursor IDE may inject PLAYWRIGHT_BROWSERS_PATH -> cursor-sandbox-cache (empty).
_pw_raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
_pw = _pw_raw.replace("\\", "/").lower()
if (not _pw) or ("cursor-sandbox-cache" in _pw) or (not os.path.exists(_pw_raw)):
    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

# Must run before importing config / main (execjs, cv2, …).
_sanitize_venv_and_project_bom()

import config

# Prefer standard Playwright persistent context (QR + login state).
config.ENABLE_CDP_MODE = False
config.CDP_CONNECT_EXISTING = False
config.HEADLESS = False
config.CDP_HEADLESS = False
if getattr(config, "CRAWLER_MAX_SLEEP_SEC", 2) < 5:
    config.CRAWLER_MAX_SLEEP_SEC = 6
if getattr(config, "MAX_CONCURRENCY_NUM", 1) != 1:
    config.MAX_CONCURRENCY_NUM = 1

# Discovery-first defaults; opt-in via Bagel .env → BAGEL_MC_GET_* .
config.ENABLE_GET_COMMENTS = _env_bool("BAGEL_MC_GET_COMMENTS", False)
config.ENABLE_GET_SUB_COMMENTS = _env_bool("BAGEL_MC_GET_SUB_COMMENTS", False)
# Upstream typo: MEIDAS = medias (images/videos). Prefer yt-dlp on /av for video study.
config.ENABLE_GET_MEIDAS = _env_bool("BAGEL_MC_GET_MEDIAS", False)

if __name__ == "__main__":
    from tools.app_runner import run
    import main as mc_main

    def _force_stop() -> None:
        c = mc_main.crawler
        if not c:
            return
        cdp_manager = getattr(c, "cdp_manager", None)
        launcher = getattr(cdp_manager, "launcher", None) if cdp_manager else None
        if not launcher:
            return
        try:
            launcher.cleanup()
        except Exception:
            pass

    run(
        mc_main.main,
        mc_main.async_cleanup,
        cleanup_timeout_seconds=15.0,
        on_first_interrupt=_force_stop,
    )
