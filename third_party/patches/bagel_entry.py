# -*- coding: utf-8 -*-
"""Bagel entry shim for MediaCrawler — force Playwright so QR login is visible.

Copied into a local MediaCrawler checkout by `bagel setup-media`.
We do NOT vendor MediaCrawler source; only this thin wrapper lives in Bagel.
"""

from __future__ import annotations

import os

# Cursor IDE may inject PLAYWRIGHT_BROWSERS_PATH -> cursor-sandbox-cache (empty).
_pw_raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
_pw = _pw_raw.replace("\\", "/").lower()
if (not _pw) or ("cursor-sandbox-cache" in _pw) or (not os.path.exists(_pw_raw)):
    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

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
config.ENABLE_GET_COMMENTS = False

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
