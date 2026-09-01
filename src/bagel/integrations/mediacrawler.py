"""MediaCrawler adapter — invokes an external checkout; never vendors its source."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from bagel.settings import Settings, get_settings

ProgressCallback = Callable[..., None]

# Platforms supported by NanmiCoder/MediaCrawler (subset we expose in UI)
MEDIA_PLATFORMS: list[tuple[str, str]] = [
    ("xhs", "小红书"),
    ("dy", "抖音"),
    ("ks", "快手"),
    ("bili", "哔哩哔哩"),
    ("wb", "微博"),
    ("tieba", "百度贴吧"),
    ("zhihu", "知乎"),
]

PLATFORM_LABELS: dict[str, str] = dict(MEDIA_PLATFORMS)

# Log snippets that mean "user action needed"
_QR_HINT_PATTERNS = (
    "waiting for scan",
    "qrcode",
    "扫码",
    "login_by_qrcode",
    "Begin login",
)
_CDP_FAIL_PATTERNS = (
    "Cannot connect to existing browser",
    "CDP browser launch failed",
    "CDP connection failed",
    "Browser failed to start within",
)
_LOGIN_FAIL_PATTERNS = (
    "have not found qrcode",
    "Login xiaohongshu failed",
    "login failed",
)
_PLAYWRIGHT_MISSING_PATTERNS = (
    "Executable doesn't exist",
    "playwright install",
    "Looks like Playwright was just installed",
    "chrome-win64",
    "chromium-",
)


@dataclass
class MediaPost:
    platform: str
    title: str
    url: str
    summary: str
    author: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class MediaCrawlResult:
    posts: list[MediaPost] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)  # platform, label, error
    hints: list[str] = field(default_factory=list)


class MediaCrawlerError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.media_active:
        return False
    path = (settings.media_crawler_path or "").strip()
    return bool(path) and Path(path).is_dir()


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    from bagel.pipeline.paths import display_path

    settings = settings or get_settings()
    path = (settings.media_crawler_path or "").strip()
    root = Path(path) if path else None
    browser = _playwright_browser_status(root) if root and root.is_dir() else {
        "ok": False,
        "detail": "MEDIA_CRAWLER_PATH 未配置",
        "executable": None,
    }
    exe = browser.get("executable")
    return {
        "enabled": settings.media_active,
        "path_configured": bool(path),
        "path_exists": bool(path) and Path(path).is_dir(),
        "path": display_path(path) if path else None,
        "platforms": settings.media_platform_list,
        "keywords": settings.media_keyword_list,
        "login_type": settings.media_crawler_login_type,
        "max_notes": settings.media_crawler_max_notes,
        "cdp_connect_existing": settings.media_crawler_cdp_connect_existing,
        "enable_cdp_mode": settings.media_crawler_enable_cdp_mode,
        "playwright_ok": bool(browser.get("ok")),
        "playwright_detail": browser.get("detail"),
        "playwright_executable": display_path(exe) if exe else None,
    }


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _decode_output(data: bytes | None) -> str:
    """Decode subprocess bytes safely on Windows (avoid default GBK crash)."""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def os_name_is_windows() -> bool:
    return os.name == "nt"


def _platform_label(code: str) -> str:
    return PLATFORM_LABELS.get(code, code)


def _normalize_keywords(keywords: list[str]) -> list[str]:
    """Split Chinese commas / spaces so 'AI 教育' becomes ['AI','教育']."""
    out: list[str] = []
    for raw in keywords:
        text = (raw or "").replace("，", ",").replace("、", ",").strip()
        if not text:
            continue
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) == 1 and (" " in parts[0] or "\u3000" in parts[0]):
            parts = [p for p in re.split(r"[\s\u3000]+", parts[0]) if p]
        out.extend(parts)
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for k in out:
        if k.lower() in seen:
            continue
        seen.add(k.lower())
        uniq.append(k)
    return uniq


def _echo_crawler_log(platform: str, line: str) -> None:
    """Always mirror MediaCrawler child logs to the parent process console."""
    text = f"[MediaCrawler/{platform}] {line}"
    try:
        print(text, flush=True)
    except Exception:
        try:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception:
            pass


def _sync_mediacrawler_browser_config(
    root: Path,
    *,
    connect_existing: bool,
    enable_cdp: bool,
    sleep_sec: int = 6,
    max_notes: int = 8,
) -> None:
    """Align MediaCrawler base_config (CLI has no CDP / sleep switches)."""
    path = root / "config" / "base_config.py"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    original = text
    for name, value in (
        ("CDP_CONNECT_EXISTING", connect_existing),
        ("ENABLE_CDP_MODE", enable_cdp),
        ("HEADLESS", False),
        ("CDP_HEADLESS", False),
    ):
        text, _n = re.subn(
            rf"{name}\s*=\s*(True|False)",
            f"{name} = {value}",
            text,
            count=1,
        )
    sleep_sec = max(3, int(sleep_sec or 6))
    max_notes = max(1, min(int(max_notes or 8), 20))
    text, _n = re.subn(
        r"CRAWLER_MAX_SLEEP_SEC\s*=\s*\d+",
        f"CRAWLER_MAX_SLEEP_SEC = {sleep_sec}",
        text,
        count=1,
    )
    text, _n = re.subn(
        r"CRAWLER_MAX_NOTES_COUNT\s*=\s*\d+",
        f"CRAWLER_MAX_NOTES_COUNT = {max_notes}",
        text,
        count=1,
    )
    if text != original:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass


def _row_to_post(row: dict[str, Any], platform: str) -> MediaPost | None:
    from bagel.pipeline.textutil import headline_from_body, strip_html

    raw_title = strip_html(str(row.get("title") or ""))
    raw_body = strip_html(str(row.get("desc") or row.get("content") or ""))
    # Weibo / many platforms only have content — never persist identical title+summary.
    body = (raw_body or raw_title)[:2000]
    if raw_title and raw_title != body and len(raw_title) <= 120:
        title = raw_title
    else:
        title = headline_from_body(body) or body or ""
    url = str(
        row.get("url")
        or row.get("note_url")
        or row.get("aweme_url")
        or row.get("video_url")
        or ""
    ).strip()
    if not title and not url:
        return None
    return MediaPost(
        platform=str(row.get("platform") or platform),
        title=title or url,
        url=url or f"mediacrawler://{row.get('note_id') or row.get('id') or title[:32]}",
        summary=body or title,
        author=str(row.get("nickname") or row.get("author") or "") or None,
        published_at=datetime.now(UTC),
        external_id=str(row.get("note_id") or row.get("aweme_id") or row.get("id") or "") or None,
        raw=row,
    )


def _collect_posts_from_data_dir(root: Path, platform: str, since_ts: float) -> list[MediaPost]:
    """Read newly written json/jsonl under data/ after a crawl."""
    candidates = [root / "data" / platform, root / "data"]
    posts: list[MediaPost] = []
    seen_keys: set[str] = set()
    # Allow slight clock skew / buffered writes
    min_mtime = since_ts - 5
    for data_root in candidates:
        if not data_root.is_dir():
            continue
        for path in sorted(data_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".json", ".jsonl"}:
                continue
            # Prefer files under this platform when scanning whole data/
            if data_root.name == "data" and platform and platform not in path.parts:
                # still allow if path parent looks like date-only dumps
                pass
            try:
                if path.stat().st_mtime < min_mtime:
                    continue
            except OSError:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            rows: list[dict[str, Any]] = []
            if path.suffix.lower() == ".jsonl":
                rows = _parse_jsonl(text)
            else:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, list):
                    rows = [r for r in payload if isinstance(r, dict)]
                elif isinstance(payload, dict):
                    nested = payload.get("data")
                    if isinstance(nested, list):
                        rows = [r for r in nested if isinstance(r, dict)]
                    else:
                        rows = [payload]
            for row in rows:
                # Infer platform from path when missing
                plat = str(row.get("platform") or platform)
                if platform and plat not in (platform, path.parent.name) and platform not in path.parts:
                    # skip other platforms when we know ours
                    if any(p != platform and p in path.parts for p in PLATFORM_LABELS):
                        continue
                post = _row_to_post(row, platform)
                if not post:
                    continue
                key = post.external_id or post.url or post.title
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                posts.append(post)
    return posts


def _diagnose_empty_crawl(log_text: str, *, platform: str) -> str:
    """Explain exit-0 / zero-post crawls using MediaCrawler log lines."""
    label = _platform_label(platform)
    lower = (log_text or "").lower()
    if "empty search response" in lower or "no more content" in lower:
        return (
            f"{label}：登录可能已成功，但搜索接口未返回笔记。"
            "请换更短关键词（如「AI」）、间隔几分钟后再试；勿连续高频抓取。"
        )
    if "non-json" in lower or "captcha" in lower or "access restricted" in lower:
        return f"{label}：搜索触发风控/验证，未落盘数据。请在弹出 Chrome 中完成验证后稍后再试。"
    if "fallback note" in lower or "saved search-card" in lower:
        return f"{label}：已尝试搜索卡片落盘，请检查 data/{platform}/jsonl。"
    if "login state result: false" in lower:
        return f"{label}：登录态无效，请重新扫码。"
    if "xhs crawler finished" in lower or "crawler finished" in lower:
        return (
            f"{label}：爬虫正常结束但未写出帖子文件。"
            f"请查看 MediaCrawler/data/{platform}/ 是否生成 jsonl；"
            "若为空，多为搜索无结果或详情接口被拦。"
        )
    return (
        f"{label}：进程退出码 0 但未解析到帖子。"
        f"请确认 data/{platform}/ 下有 jsonl，并避免多关键词连抓。"
    )


def _venv_python(root: Path) -> Path | None:
    candidate = root / (
        ".venv/Scripts/python.exe" if os_name_is_windows() else ".venv/bin/python"
    )
    return candidate if candidate.is_file() else None


def _child_env() -> dict[str, str]:
    env = {**os.environ}
    for key in (
        "VIRTUAL_ENV",
        "UV_PROJECT",
        "UV_PROJECT_ENVIRONMENT",
        "PYTHONHOME",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
    ):
        env.pop(key, None)
    # Cursor / sandbox often injects PLAYWRIGHT_BROWSERS_PATH pointing at a cache
    # without chrome.exe — MediaCrawler then exits instantly with no visible window.
    pw_path = (env.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if not pw_path or "cursor-sandbox-cache" in pw_path.replace("\\", "/").lower():
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    elif pw_path and not Path(pw_path).exists():
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Avoid Rich/Typer box-drawing banners being the only "error" we surface.
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    # Prefer installed Google Chrome so a window pops even without playwright install.
    env.setdefault("MEDIA_CRAWLER_USE_SYSTEM_CHROME", "1")
    return env


def _playwright_browser_status(root: Path | None) -> dict[str, Any]:
    """Probe whether Playwright Chromium is installed for MediaCrawler's venv."""
    if root is None or not root.is_dir():
        return {"ok": False, "detail": "MediaCrawler 目录无效", "executable": None}
    py = _venv_python(root)
    if py is None:
        return {"ok": False, "detail": "缺少 MediaCrawler .venv", "executable": None}
    probe = (
        "import os,sys\n"
        "os.environ.pop('PLAYWRIGHT_BROWSERS_PATH', None)\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    path = p.chromium.executable_path\n"
        "    print(path)\n"
        "    sys.exit(0 if path and __import__('pathlib').Path(path).is_file() else 2)\n"
    )
    try:
        proc = subprocess.run(
            [str(py), "-c", probe],
            cwd=str(root),
            capture_output=True,
            text=False,
            timeout=60,
            env=_child_env(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "detail": f"探测失败：{exc}", "executable": None}
    out = _decode_output(proc.stdout).strip().splitlines()
    exe = out[-1].strip() if out else ""
    err = _decode_output(proc.stderr)
    if proc.returncode == 0 and exe and Path(exe).is_file():
        return {"ok": True, "detail": "Playwright Chromium 就绪", "executable": exe}
    combined = f"{err}\n{_decode_output(proc.stdout)}"
    if any(p.lower() in combined.lower() for p in _PLAYWRIGHT_MISSING_PATTERNS):
        return {
            "ok": False,
            "detail": "未安装 Playwright Chromium（浏览器无法弹窗）",
            "executable": None,
        }
    return {
        "ok": False,
        "detail": (err or _decode_output(proc.stdout) or "Chromium 不可用")[:240],
        "executable": exe or None,
    }


def _ensure_playwright_browsers(
    root: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    # Default path: use system Chrome (channel=chrome). Skip heavy chromium download.
    use_system = os.getenv("MEDIA_CRAWLER_USE_SYSTEM_CHROME", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if use_system:
        if on_progress:
            on_progress(
                current=0,
                total=100,
                percent=2.0,
                message="将使用本机 Google Chrome 弹窗扫码（不依赖 Playwright 内核下载）…",
            )
        return

    status = _playwright_browser_status(root)
    if status.get("ok"):
        return
    py = _venv_python(root)
    if py is None:
        raise MediaCrawlerError(
            "MediaCrawler .venv 不存在，无法启动浏览器。请先在 third_party/MediaCrawler 安装依赖。"
        )
    if on_progress:
        on_progress(
            current=0,
            total=100,
            percent=3.0,
            message="正在安装 Playwright Chromium（首次约需几分钟，完成后才会弹窗）…",
        )
    try:
        proc = subprocess.run(
            [str(py), "-m", "playwright", "install", "chromium"],
            cwd=str(root),
            capture_output=True,
            text=False,
            timeout=60 * 20,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaCrawlerError("playwright install chromium 超时，请在 MediaCrawler 目录手动执行该命令") from exc
    except OSError as exc:
        raise MediaCrawlerError(f"无法执行 playwright install：{exc}") from exc
    if proc.returncode != 0:
        err = (_decode_output(proc.stderr) or _decode_output(proc.stdout))[:300]
        raise MediaCrawlerError(
            "Playwright Chromium 安装失败，浏览器无法弹窗。"
            f"请在 MediaCrawler 目录手动执行：.venv\\Scripts\\python.exe -m playwright install chromium。"
            f" 详情：{err}"
        )
    status = _playwright_browser_status(root)
    if not status.get("ok"):
        raise MediaCrawlerError(
            "Playwright Chromium 仍不可用（常见原因：环境变量 PLAYWRIGHT_BROWSERS_PATH 指向 Cursor 沙箱空目录）。"
            f" 详情：{status.get('detail')}"
        )


def _pick_meaningful_error_line(text: str) -> str:
    """Skip Rich box-drawing banners; prefer real exception / playwright hints."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    scored: list[tuple[int, str]] = []
    for ln in lines:
        # Box-drawing / decorative lines
        if re.fullmatch(r"[═║╔╗╚╝�\s\|─]+", ln) or ln.startswith("╚") or ln.startswith("╔"):
            continue
        if set(ln) <= set("═║╔╗╚╝─│┌┐└┘█■□?� "):
            continue
        score = 0
        lower = ln.lower()
        if "error" in lower or "exception" in lower or "traceback" in lower:
            score += 5
        if any(p.lower() in lower for p in _PLAYWRIGHT_MISSING_PATTERNS):
            score += 8
        if "executable" in lower or "playwright" in lower:
            score += 4
        if ln.startswith("File ") or "line " in lower:
            score += 1
        if score:
            scored.append((score, ln))
    if scored:
        scored.sort(key=lambda x: x[0])
        return scored[-1][1]
    # Fallback: last non-decorative line
    for ln in reversed(lines):
        if not re.match(r"^[═║╔╗╚╝�\s\|─]+$", ln):
            return ln
    return lines[-1]


def _humanize_error(raw: str, *, platform: str) -> str:
    text = (raw or "").strip()
    lower = text.lower()
    label = _platform_label(platform)
    if any(p.lower() in lower for p in _PLAYWRIGHT_MISSING_PATTERNS) or "executable doesn't exist" in lower:
        return (
            f"{label}：浏览器内核启动失败（无弹窗）。"
            "请确认本机已安装 Google Chrome；并清除指向 cursor-sandbox-cache 的 "
            "PLAYWRIGHT_BROWSERS_PATH 后重启服务。备选：在 MediaCrawler 目录执行 "
            ".venv\\Scripts\\python.exe -m playwright install chromium。"
        )
    if "jsondecodeerror" in lower or "non-json" in lower or "expecting value" in lower:
        return (
            f"{label}：接口返回了非 JSON（多为风控/验证页）。"
            "登录虽成功，但请求过密仍会触发。请减少关键词（建议 1 个）、降低笔记数，"
            "间隔数分钟后再试；勿短时间反复点「开始抓取」。"
        )
    if "captcha" in lower or "security restriction" in lower or "platformaccesserror" in lower:
        return (
            f"{label}：触发平台风控/验证。"
            "请暂停抓取、在弹出的 Chrome 中手动完成验证后，间隔更长时间再试。"
        )
    if any(p.lower() in lower or p in text for p in _CDP_FAIL_PATTERNS):
        return (
            f"{label}：浏览器 CDP 启动/连接失败。"
            "请确认 MEDIA_CRAWLER_ENABLE_CDP_MODE=false，重启后重试。"
        )
    if any(p.lower() in lower or p in text for p in _LOGIN_FAIL_PATTERNS):
        return (
            f"{label}：未完成扫码登录（页面未出现二维码或超时）。"
            "请在弹出的浏览器窗口内手动打开登录弹层并扫码；不要关窗口。"
        )
    if "invalid media platform" in lower or "not within the supported" in lower:
        return f"{label}：平台参数无效（MediaCrawler 每次只能跑一个平台）"
    if "timeout" in lower:
        return f"{label}：超时（扫码未完成或浏览器卡住）"
    tail = _pick_meaningful_error_line(text)
    if len(tail) > 220:
        tail = tail[:220] + "…"
    return f"{label}：{tail or '未知错误（进程异常退出且无有效日志）'}"


def _build_cmd(
    *,
    root: Path,
    settings: Settings,
    platform: str,
    keywords: list[str],
) -> list[str]:
    venv_python = root / (
        ".venv/Scripts/python.exe" if os_name_is_windows() else ".venv/bin/python"
    )
    entry_candidates = ("bagel_entry.py", "intel_center_entry.py", "main.py")
    entry = next((name for name in entry_candidates if (root / name).is_file()), "main.py")
    # Prefer wrapper that forces ENABLE_CDP_MODE=False before main runs.
    script = entry
    if venv_python.is_file():
        base = [str(venv_python), script]
    else:
        base = settings.media_crawler_cmd.strip().split()
        if not base:
            raise MediaCrawlerError("MEDIA_CRAWLER_CMD 为空")
        # Replace trailing main.py with our entry when present.
        if entry != "main.py" and base[-1].endswith("main.py"):
            base = [*base[:-1], entry]

    login = (settings.media_crawler_login_type or "qrcode").strip() or "qrcode"
    # QR login needs a visible browser; cookie mode can stay non-headless for CAPTCHA.
    headless = "false"
    return [
        *base,
        "--platform",
        platform,
        "--lt",
        login,
        "--type",
        "search",
        "--keywords",
        ",".join(keywords),
        "--save_data_option",
        "jsonl",
        "--crawler_max_notes_count",
        str(settings.media_crawler_max_notes),
        "--get_comment",
        "false",
        "--headless",
        headless,
    ]


def _run_one_platform(
    *,
    root: Path,
    settings: Settings,
    platform: str,
    keywords: list[str],
    index: int,
    total: int,
    on_progress: ProgressCallback | None,
) -> tuple[list[MediaPost], str | None]:
    """Run MediaCrawler once for a single platform. Returns (posts, error_or_None)."""
    label = _platform_label(platform)
    cmd = _build_cmd(root=root, settings=settings, platform=platform, keywords=keywords)
    login = (settings.media_crawler_login_type or "qrcode").strip()
    # Each platform owns 100 progress units so a single-platform crawl is not stuck at 0%.
    units = 100
    span = max(total, 1) * units

    def _emit(phase: int, message: str) -> None:
        if not on_progress:
            return
        phase = max(0, min(units, int(phase)))
        current = (index - 1) * units + phase
        percent = round(100.0 * current / span, 1)
        on_progress(
            current=current,
            total=span,
            message=f"[{index}/{total}] {message}",
            percent=min(99.0, percent),
        )

    print(f"[MediaCrawler/{platform}] cwd={root}", flush=True)
    print(f"[MediaCrawler/{platform}] cmd={' '.join(cmd)}", flush=True)

    if login == "qrcode":
        _emit(5, f"{label}：启动中（首次请在弹出窗口扫码，最长约 20 分钟）…")
    else:
        _emit(5, f"{label}：启动浏览器…")

    started = time.time()
    log_chunks: list[str] = []
    phase = 5
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_child_env(),
            text=False,
        )
    except FileNotFoundError as exc:
        return [], f"无法执行 MediaCrawler：{exc}"

    def _reader() -> None:
        nonlocal phase
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.readline()
            if not chunk:
                break
            line = _decode_output(chunk).rstrip()
            if not line:
                continue
            log_chunks.append(line)
            _echo_crawler_log(platform, line)
            # Cap stored log
            if len(log_chunks) > 800:
                del log_chunks[:200]
            lower = line.lower()
            if any(p.lower() in lower or p in line for p in _QR_HINT_PATTERNS):
                phase = max(phase, 20)
                _emit(phase, f"{label}：等待扫码/验证登录（看弹出窗口，最长约 20 分钟）…")
            elif "launching browser" in lower or "cdpbrowsermanager" in lower:
                phase = max(phase, 12)
                _emit(phase, f"{label}：连接/启动浏览器…")
            elif "login successful" in lower or "login status confirmed" in lower:
                phase = max(phase, 40)
                _emit(phase, f"{label}：登录成功，开始抓取…")
            elif "no more content" in lower or "empty search" in lower:
                phase = max(phase, 85)
                _emit(phase, f"{label}：搜索无结果，将结束该平台…")
            elif "saved search-card" in lower or "update_xhs_note" in lower or "save note" in lower:
                phase = max(phase, min(80, phase + 2))
                _emit(phase, f"{label}：正在写入笔记…")
            elif ("crawler" in lower and "start" in lower) or "search" in lower:
                phase = max(phase, 45)
                _emit(phase, f"{label}：正在抓取…")

    reader = threading.Thread(target=_reader, name=f"mc-log-{platform}", daemon=True)
    reader.start()

    # Soft heartbeat so UI advances while waiting for QR / network.
    deadline = started + 60 * 30
    last_heartbeat_bucket = -1
    while proc.poll() is None:
        if time.time() > deadline:
            proc.kill()
            reader.join(timeout=5)
            return [], f"{label}：超时（>30min）"
        elapsed = int(time.time() - started)
        bucket = elapsed // 5
        if on_progress and bucket != last_heartbeat_bucket:
            last_heartbeat_bucket = bucket
            # Creep forward within the current band (cap before "done").
            if phase < 20:
                phase = min(18, 5 + elapsed // 10)
            elif phase < 40:
                phase = min(38, 20 + elapsed // 15)
            elif phase < 70:
                phase = min(68, 40 + elapsed // 20)
            tip = f"{label}：运行中…已 {elapsed}s"
            if login == "qrcode" and phase < 40:
                tip += "（若需登录请扫码）"
            _emit(phase, tip)
        time.sleep(1)

    reader.join(timeout=10)
    combined = "\n".join(log_chunks[-120:])
    # Persist last crawl log for offline debugging
    try:
        log_path = Path(settings.data_dir) / "mediacrawler_last.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# platform={platform} keywords={keywords} returncode={proc.returncode} "
            f"elapsed={int(time.time() - started)}s\n"
        )
        log_path.write_text(header + "\n".join(log_chunks[-500:]), encoding="utf-8")
        from bagel.pipeline.paths import display_path

        print(f"[MediaCrawler/{platform}] wrote {display_path(log_path)}", flush=True)
    except OSError as exc:
        print(f"[MediaCrawler/{platform}] failed to write last log: {exc}", flush=True)

    posts = _collect_posts_from_data_dir(root, platform, since_ts=started)

    # Also parse any JSONL spilled to stdout
    for row in _parse_jsonl(combined):
        post = _row_to_post(row, platform)
        if post:
            posts.append(post)

    if proc.returncode != 0 and not posts:
        return [], _humanize_error(combined, platform=platform)

    if not posts:
        # Exit 0 but nothing stored — surface actionable diagnosis (not a hard crash).
        diag = _diagnose_empty_crawl(combined, platform=platform)
        _emit(100, diag)
        return [], diag

    _emit(100, f"{label}：完成，解析到 {len(posts)} 条")
    return posts, None


def run_media_crawl(
    *,
    platforms: list[str] | None = None,
    keywords: list[str] | None = None,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> MediaCrawlResult:
    """
    Spawn MediaCrawler **once per platform** (MediaCrawler accepts a single --platform).

    Failed platforms are skipped; successful ones still ingest. Progress updates while
    the child process runs (so the UI is not stuck at 0%).
    """
    settings = settings or get_settings()
    if not settings.media_active:
        raise MediaCrawlerError("未启用自媒体采集：请在 .env 设置 ENABLE_MEDIA_CRAWLER=true")
    root = Path((settings.media_crawler_path or "").strip())
    if not root.is_dir():
        raise MediaCrawlerError(
            "MEDIA_CRAWLER_PATH 未配置或不存在。请克隆 MediaCrawler 并写入 .env。"
        )

    plats = [p.strip() for p in (platforms or settings.media_platform_list) if p and p.strip()]
    kws = _normalize_keywords(keywords or settings.media_keyword_list)
    if not plats:
        raise MediaCrawlerError("请至少选择一个平台")
    if not kws:
        raise MediaCrawlerError("请至少填写一个关键词")

    max_kw = max(1, int(getattr(settings, "media_crawler_max_keywords", 2) or 2))
    capped = False
    if len(kws) > max_kw:
        kws = kws[:max_kw]
        capped = True

    print(
        f"[MediaCrawler] start platforms={plats} keywords={kws} "
        f"max_notes={settings.media_crawler_max_notes} "
        f"sleep={getattr(settings, 'media_crawler_sleep_sec', 6)}",
        flush=True,
    )

    # Prefer Playwright (no CDP :9222). Entry script also forces this in-process.
    _sync_mediacrawler_browser_config(
        root,
        connect_existing=settings.media_crawler_cdp_connect_existing,
        enable_cdp=settings.media_crawler_enable_cdp_mode,
        sleep_sec=int(getattr(settings, "media_crawler_sleep_sec", 6) or 6),
        max_notes=int(settings.media_crawler_max_notes or 8),
    )
    # Without Chromium binary there is no popup window — fail fast / auto-install.
    _ensure_playwright_browsers(root, on_progress=on_progress)

    result = MediaCrawlResult()
    if capped:
        result.hints.append(
            f"为降低风控，本次仅使用前 {max_kw} 个关键词：{', '.join(kws)}。"
            "建议每次只填 1 个关键词，间隔数分钟再抓。"
        )
    total = len(plats)
    span = max(total, 1) * 100
    if on_progress:
        on_progress(
            current=0,
            total=span,
            percent=1.0,
            message=(
                f"将依次抓取 {total} 个平台 · 关键词 {','.join(kws)} · "
                f"限 {settings.media_crawler_max_notes} 条 · "
                f"间隔 {getattr(settings, 'media_crawler_sleep_sec', 6)}s…"
            ),
        )

    for i, platform in enumerate(plats, start=1):
        try:
            posts, err = _run_one_platform(
                root=root,
                settings=settings,
                platform=platform,
                keywords=kws,
                index=i,
                total=total,
                on_progress=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            posts, err = [], f"{_platform_label(platform)}：{exc}"

        if err:
            result.failed.append(
                {
                    "platform": platform,
                    "label": _platform_label(platform),
                    "error": err,
                }
            )
            if on_progress:
                done = i * 100
                on_progress(
                    current=done,
                    total=span,
                    percent=min(99.0, round(100.0 * done / span, 1)),
                    message=f"[{i}/{total}] {_platform_label(platform)} 失败，已跳过 → {err[:120]}",
                )
            continue

        result.succeeded.append(platform)
        result.posts.extend(posts)

    if result.failed and not result.posts:
        # All platforms failed → raise so job marks FAILED with a clear message
        parts = [f["error"] for f in result.failed]
        hint = ""
        if any("CDP" in e or "Playwright" in e or "扫码" in e for e in parts):
            hint = (
                " 提示：请确认 MEDIA_CRAWLER_ENABLE_CDP_MODE=false，重启后重试；"
                "日志应出现 standard mode，并在弹出浏览器中扫码。"
            )
        raise MediaCrawlerError("；".join(parts) + hint)

    if result.failed:
        result.hints.append(
            "部分平台失败已跳过："
            + "；".join(f"{f['label']}" for f in result.failed)
            + "。多平台会依次抓取，每个平台首次可能都要扫码。"
        )
    if (settings.media_crawler_login_type or "").strip() == "qrcode":
        result.hints.append(
            "扫码位置：MediaCrawler 弹出的浏览器窗口，或桌面二维码图片窗口（不是本网页）。"
            "登录成功后会写入浏览器用户目录，下次同平台通常无需再扫。"
        )

    if on_progress:
        on_progress(
            current=span,
            total=span,
            percent=99.0,
            message=(
                f"全部结束：成功 {len(result.succeeded)} / 失败 {len(result.failed)}，"
                f"共 {len(result.posts)} 条，准备入库…"
            ),
        )
    return result
