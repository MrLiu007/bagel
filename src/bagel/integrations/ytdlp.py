"""yt-dlp adapter — invokes an external checkout; never vendors its source."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from bagel.settings import Settings, get_settings

ProgressCallback = Callable[..., None]

logger = logging.getLogger("bagel.ytdlp")

_DOWNLOAD_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
_SURFACE_KEYS = (
    "[download]",
    "error",
    "warning",
    "extracting",
    "destination",
    "cookie",
    "http error",
    "downloading",
    "merging",
    "deleting",
    "writing",
)

AV_PLATFORMS: list[tuple[str, str]] = [
    ("youtube", "YouTube"),
    ("bilibili", "哔哩哔哩"),
    ("douyin", "抖音"),
    ("kuaishou", "快手"),
    ("vimeo", "Vimeo"),
    ("coursera", "Coursera"),
    ("edx", "edX"),
    ("mooc", "中国大学MOOC"),
    ("generic", "其他"),
]

PLATFORM_LABELS: dict[str, str] = dict(AV_PLATFORMS)

# av:source URL prefixes (stored in IntelSource.url)
_PREFIX = "av:"


@dataclass
class AvEntry:
    title: str
    url: str
    external_id: str | None = None
    platform: str = "generic"
    media_kind: str = "video"
    duration_sec: int | None = None
    author: str | None = None
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    description: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class AvExtractResult:
    entries: list[AvEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class YtdlpError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.ytdlp_active:
        return False
    path = (settings.ytdlp_path or "").strip()
    return bool(path) and Path(path).is_dir()


def _resolve_root(settings: Settings) -> Path:
    raw = (settings.ytdlp_path or "").strip() or "./third_party/yt-dlp"
    root = Path(raw)
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root


def _ytdlp_executable(root: Path) -> list[str]:
    from bagel.services.ytdlp_setup import venv_python, venv_ytdlp

    exe = venv_ytdlp(root)
    if exe.is_file():
        return [str(exe)]
    py = venv_python(root)
    if py.is_file():
        return [str(py), "-m", "yt_dlp"]
    raise YtdlpError(
        "yt-dlp 可执行文件未找到。请在 third_party/yt-dlp 创建 .venv 并安装依赖 "
        "（bagel setup-ytdlp）。"
    )


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    from bagel.pipeline.paths import display_path
    from bagel.services.ytdlp_setup import checkout_ref, is_checkout_ready, is_venv_ready

    settings = settings or get_settings()
    path = (settings.ytdlp_path or "").strip()
    root = _resolve_root(settings) if path else None
    ffmpeg_ok = _ffmpeg_status(settings)
    pinned = (settings.ytdlp_git_ref or "").strip() or None
    actual = checkout_ref(root) if root else None
    return {
        "enabled": settings.ytdlp_active,
        "path_configured": bool(path),
        "path_exists": bool(root and root.is_dir()),
        "checkout_ready": bool(root and is_checkout_ready(root)),
        "venv_ready": bool(root and is_venv_ready(root)),
        "path": display_path(path) if path else None,
        "git_ref_pinned": pinned,
        "git_ref_actual": actual,
        "outdated": bool(pinned and actual and pinned not in actual),
        "ffmpeg_ok": ffmpeg_ok.get("ok"),
        "ffmpeg_detail": ffmpeg_ok.get("detail"),
        "max_items_per_source": settings.av_max_items_per_source,
        "default_audio_only": settings.av_default_audio_only,
        "cookies_browser": (settings.av_cookies_from_browser or settings.av_bilibili_browser or "").strip() or None,
    }


def _ffmpeg_status(settings: Settings) -> dict[str, Any]:
    from bagel.pipeline.paths import display_path
    from shutil import which

    ff = (settings.ffmpeg_path or "").strip()
    if ff and Path(ff).is_file():
        return {"ok": True, "detail": display_path(ff)}
    found = which("ffmpeg")
    if found:
        return {"ok": True, "detail": display_path(found)}
    return {"ok": False, "detail": "未检测到 ffmpeg（可选；缺失时部分格式无法合并/转码）"}


def parse_av_source_url(raw: str) -> tuple[str, str]:
    """Return (platform_key, resolved_http_url) from IntelSource.url."""
    text = (raw or "").strip()
    if not text.lower().startswith(_PREFIX):
        if text.startswith("http://") or text.startswith("https://"):
            return _platform_from_url(text), text
        raise YtdlpError(f"无效音视频源 URL：{text[:120]}")

    body = text[len(_PREFIX) :]
    if body.startswith("youtube:channel:"):
        handle = body.split(":", 2)[2]
        if handle.startswith("@"):
            return "youtube", f"https://www.youtube.com/{handle}/videos"
        return "youtube", f"https://www.youtube.com/channel/{handle}/videos"
    if body.startswith("youtube:playlist:"):
        pid = body.split(":", 2)[2]
        return "youtube", f"https://www.youtube.com/playlist?list={pid}"
    if body.startswith("bilibili:mid:"):
        mid = body.split(":", 2)[2]
        return "bilibili", f"https://space.bilibili.com/{mid}/video"
    if body.startswith("bilibili:season:"):
        sid = body.split(":", 2)[2]
        return "bilibili", f"https://space.bilibili.com/999999999/channel/seriesdetail?sid={sid}"
    if body.startswith("generic:url:"):
        url = unquote(body.split(":", 2)[2])
        return _platform_from_url(url), url
    if body.startswith("url:"):
        url = unquote(body[len("url:") :])
        return _platform_from_url(url), url
    raise YtdlpError(f"无法解析音视频源：{text[:120]}")


def _platform_from_url(url: str) -> str:
    lower = url.lower()
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if "bilibili.com" in lower or "b23.tv" in lower:
        return "bilibili"
    if "douyin.com" in lower or "iesdouyin.com" in lower:
        return "douyin"
    if "kuaishou.com" in lower or "chenzhongtech.com" in lower:
        return "kuaishou"
    if "vimeo.com" in lower:
        return "vimeo"
    if "coursera.org" in lower:
        return "coursera"
    if "edx.org" in lower:
        return "edx"
    if "icourse163.org" in lower:
        return "mooc"
    if "open.163.com" in lower:
        return "mooc"
    if "xuetangx.com" in lower:
        return "mooc"
    return "generic"


def _parse_upload_date(value: str | None) -> datetime | None:
    if not value or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime(
            int(value[0:4]),
            int(value[4:6]),
            int(value[6:8]),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _row_to_entry(row: dict[str, Any], *, default_platform: str) -> AvEntry | None:
    if not isinstance(row, dict):
        return None
    url = (row.get("webpage_url") or row.get("url") or row.get("original_url") or "").strip()
    if not url and row.get("id"):
        url = f"ytdlp://{row.get('id')}"
    title = (row.get("title") or row.get("id") or "").strip()
    if not title:
        return None
    extractor = (row.get("extractor_key") or row.get("extractor") or "").lower()
    platform = default_platform
    if "youtube" in extractor:
        platform = "youtube"
    elif "bili" in extractor:
        platform = "bilibili"
    elif "vimeo" in extractor:
        platform = "vimeo"
    elif "coursera" in extractor:
        platform = "coursera"
    elif "edx" in extractor:
        platform = "edx"
    duration = row.get("duration")
    media_kind = "audio" if row.get("vcodec") == "none" else "video"
    if row.get("duration") is None and row.get("_type") == "playlist":
        return None
    return AvEntry(
        title=title[:500],
        url=url,
        external_id=str(row.get("id") or "") or None,
        platform=platform,
        media_kind=media_kind,
        duration_sec=int(duration) if duration is not None else None,
        author=(row.get("uploader") or row.get("channel") or row.get("artist") or None),
        published_at=_parse_upload_date(row.get("upload_date")),
        thumbnail_url=row.get("thumbnail"),
        description=(row.get("description") or "")[:2000] or None,
        raw=row,
    )


def _friendly_ytdlp_error(raw: str, *, platform: str = "") -> str:
    text = (raw or "").strip()
    lower = text.lower()
    if "could not copy" in lower or "cookie database" in lower:
        site = "douyin.com" if platform == "douyin" else "bilibili.com"
        return (
            "无法读取浏览器 Cookie（常见原因：Chrome 正在运行并锁定了 Cookie 库）。"
            "请关闭 Chrome 后重试，或改用 Edge：.env 设置 AV_COOKIES_FROM_BROWSER=edge，"
            f"并先在该浏览器打开 {site}（不必登录账号，但需要最近访问过）。"
        )
    if "412" in lower or "precondition failed" in lower:
        if platform == "bilibili" or "bili" in lower:
            return (
                "B 站返回 HTTP 412（反爬校验）。请：① 升级 yt-dlp"
                "（uv run bagel setup-ytdlp --ref 2026.08.19）；"
                "② 在 Edge 打开 bilibili.com 后设置 AV_COOKIES_FROM_BROWSER=edge；"
                "③ 关闭 Chrome 再点下载。"
            )
        return (
            "上游返回 HTTP 412。请升级 yt-dlp，并配置浏览器 Cookie"
            "（AV_COOKIES_FROM_BROWSER=edge）。"
        )
    if (
        "fresh cookies" in lower
        or ("cookies" in lower and "needed" in lower)
        or "login" in lower
        or "cookies" in lower
        or "rejected" in lower
    ):
        if platform == "douyin":
            return (
                "抖音下载/提字幕需要浏览器 Cookie（yt-dlp：Fresh cookies are needed）。"
                "请：① 用 Edge 打开 https://www.douyin.com 随便刷几条；"
                "② .env 设置 AV_COOKIES_FROM_BROWSER=edge（或 chrome）；"
                "③ 关闭该浏览器后再点「下载并解析文稿」。"
                "也可用浏览器扩展导出 cookies.txt，设置 AV_COOKIES_FILE=路径。"
            )
        if platform == "kuaishou":
            return (
                "快手需要浏览器 Cookie。请先在 Edge 打开 kuaishou.com，"
                "设置 AV_COOKIES_FROM_BROWSER=edge，关闭浏览器后重试。"
            )
        if platform == "bilibili" or "bili" in lower:
            return (
                "B 站 UP 主页列表需要浏览器登录态。"
                "请先在 Edge 登录 bilibili.com（建议关掉 Chrome），并在 .env 设置 "
                "AV_COOKIES_FROM_BROWSER=edge。"
            )
        return (
            "该平台需要登录 Cookie。请关闭浏览器后重试，或在 .env 设置 "
            "AV_COOKIES_FROM_BROWSER=edge（或 AV_COOKIES_FILE 指向 cookies.txt）。"
        )
    if "ffmpeg" in lower:
        return "缺少 ffmpeg，部分格式无法处理。可安装 ffmpeg 或仅采集元数据。"
    return text[:400]


# Platforms where yt-dlp usually refuses bare (no-cookie) requests.
_COOKIE_PREFERRED_PLATFORMS = frozenset({"bilibili", "douyin", "kuaishou"})


def _cookie_attempts(settings: Settings, platform: str) -> list[str | None]:
    """Browsers to try; cookie-heavy sites default to edge/chrome before bare."""
    cookies_file = (settings.av_cookies_file or "").strip()
    if cookies_file and Path(cookies_file).is_file():
        return [None]

    ordered: list[str | None] = []

    def _add(name: str | None) -> None:
        if name not in ordered:
            ordered.append(name)

    explicit = (settings.av_cookies_from_browser or "").strip()
    if explicit:
        for part in explicit.split(","):
            if part.strip():
                _add(part.strip().lower())
    elif platform in _COOKIE_PREFERRED_PLATFORMS:
        raw = (settings.av_bilibili_browser or "edge,chrome").strip() or "edge,chrome"
        for part in raw.split(","):
            if part.strip():
                _add(part.strip().lower())

    # Douyin / 快手：补齐常见浏览器，且不做无 Cookie 空跑。
    if platform in {"douyin", "kuaishou"}:
        _add("edge")
        _add("chrome")
        return ordered

    _add(None)
    return ordered


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _platform_extra_args(platform: str) -> list[str]:
    """Site-specific headers that reduce anti-bot 412/403 failures."""
    if platform == "bilibili":
        return [
            "--user-agent",
            _BROWSER_UA,
            "--add-header",
            "Referer:https://www.bilibili.com/",
            "--add-header",
            "Origin:https://www.bilibili.com",
        ]
    if platform == "douyin":
        return [
            "--user-agent",
            _BROWSER_UA,
            "--add-header",
            "Referer:https://www.douyin.com/",
            "--add-header",
            "Origin:https://www.douyin.com",
        ]
    if platform == "kuaishou":
        return [
            "--user-agent",
            _BROWSER_UA,
            "--add-header",
            "Referer:https://www.kuaishou.com/",
        ]
    return []


def _build_base_cmd(
    settings: Settings,
    root: Path,
    *,
    browser: str | None = None,
    platform: str = "",
    show_progress: bool = False,
) -> list[str]:
    cmd = [*_ytdlp_executable(root), "--no-warnings"]
    if show_progress:
        # Line-based progress so we can stream percent to UI / console.
        cmd.append("--newline")
    else:
        cmd.append("--no-progress")
    env_proxy = settings.proxy_url
    if env_proxy:
        cmd.extend(["--proxy", env_proxy])
    cookies = (settings.av_cookies_file or "").strip()
    if cookies and Path(cookies).is_file():
        cmd.extend(["--cookies", cookies])
    elif browser:
        cmd.extend(["--cookies-from-browser", browser])
    ff = (settings.ffmpeg_path or "").strip()
    if ff:
        cmd.extend(["--ffmpeg-location", ff])
    cmd.extend(_platform_extra_args(platform))
    return cmd


def _should_surface_line(line: str) -> bool:
    lower = (line or "").lower()
    return any(k in lower for k in _SURFACE_KEYS)


def parse_download_percent(line: str) -> float | None:
    """Extract yt-dlp `[download] 12.3%` progress, if present."""
    m = _DOWNLOAD_PCT_RE.search(line or "")
    if not m:
        return None
    try:
        return max(0.0, min(100.0, float(m.group(1))))
    except ValueError:
        return None


def _run_ytdlp(
    cmd: list[str],
    *,
    root: Path,
    settings: Settings,
    timeout: int,
    on_line: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run yt-dlp; stream stdout/stderr lines to logger + optional callback."""
    env = _subprocess_env(settings)
    if on_line is None:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(root),
            env=env,
        )

    logger.info("yt-dlp exec: %s", " ".join(cmd[:12]) + (" …" if len(cmd) > 12 else ""))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(root),
        env=env,
        bufsize=1,
    )
    lines: list[str] = []
    lock = threading.Lock()

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n\r")
            if not line:
                continue
            with lock:
                lines.append(line)
            logger.info("yt-dlp | %s", line[:500])
            try:
                on_line(line)
            except Exception:  # noqa: BLE001 — never break the download on UI callback
                logger.exception("yt-dlp on_line callback failed")

    reader = threading.Thread(target=_reader, name="ytdlp-stdout", daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        reader.join(timeout=5)
        raise subprocess.TimeoutExpired(cmd, timeout) from exc
    reader.join(timeout=30)
    text = "\n".join(lines)
    return subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout=text, stderr="")


def _is_retryable_412(stderr: str) -> bool:
    lower = (stderr or "").lower()
    return "412" in lower or "precondition failed" in lower


def _run_with_cookie_attempts(
    extra_args: list[str],
    *,
    settings: Settings,
    root: Path,
    platform: str,
    timeout: int,
    on_progress: ProgressCallback | None = None,
    show_progress: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Retry browsers when Chrome locks its cookie DB; last attempt has no cookies.

    Bilibili may return HTTP 412 intermittently — retry the same cookie source once.
    Streams yt-dlp lines to logger and optional on_progress(log_line=…).
    """
    proc: subprocess.CompletedProcess[str] | None = None
    last_err = ""
    preferred_err = ""
    last_ui_pct = -1.0
    last_ui_ts = 0.0

    def _emit_line(line: str) -> None:
        nonlocal last_ui_pct, last_ui_ts
        if not on_progress:
            return
        dl_pct = parse_download_percent(line)
        now = time.monotonic()
        if dl_pct is not None:
            # Map extractor download 0–100 → UI band 20–95.
            ui_pct = round(20.0 + 0.75 * dl_pct, 1)
            if ui_pct - last_ui_pct >= 1.0 or now - last_ui_ts >= 1.5:
                last_ui_pct = ui_pct
                last_ui_ts = now
                on_progress(
                    current=int(ui_pct),
                    total=100,
                    message=line[:160],
                    percent=ui_pct,
                    log_line=line[:300],
                )
            return
        if _should_surface_line(line):
            on_progress(
                message=line[:160],
                log_line=line[:300],
            )

    for browser in _cookie_attempts(settings, platform):
        attempts = 2 if (platform == "bilibili" and browser is not None) else 1
        for attempt_i in range(attempts):
            cookie_label = (
                f"cookies 文件"
                if (settings.av_cookies_file or "").strip() and Path(settings.av_cookies_file).is_file()
                else (f"浏览器 Cookie={browser}" if browser else "无 Cookie")
            )
            if on_progress:
                on_progress(
                    message=f"yt-dlp 尝试 {cookie_label}"
                    + (f"（重试 {attempt_i + 1}）" if attempt_i else "")
                    + "…",
                    log_line=f"attempt {cookie_label}",
                )
            cmd = [
                *_build_base_cmd(
                    settings,
                    root,
                    browser=browser,
                    platform=platform,
                    show_progress=show_progress,
                ),
                *extra_args,
            ]
            try:
                proc = _run_ytdlp(
                    cmd,
                    root=root,
                    settings=settings,
                    timeout=timeout,
                    on_line=_emit_line if (on_progress or show_progress) else None,
                )
            except subprocess.TimeoutExpired as exc:
                raise YtdlpError(f"yt-dlp 超时（{timeout}s）") from exc
            except OSError as exc:
                raise YtdlpError(f"无法执行 yt-dlp：{exc}") from exc
            if proc.returncode == 0:
                return proc
            last_err = (proc.stderr or proc.stdout or "")[:800]
            if on_progress and last_err:
                tail = last_err.strip().splitlines()[-1][:200] if last_err.strip() else last_err[:200]
                on_progress(message=f"失败：{tail}", log_line=tail)
            if browser is not None and not preferred_err:
                preferred_err = last_err
            # Only retry same browser on 412; other errors try next cookie source.
            if not _is_retryable_412(last_err):
                break
    assert proc is not None
    # Prefer cookie-attempt error over bare no-cookie 412 (clearer guidance).
    raise YtdlpError(_friendly_ytdlp_error(preferred_err or last_err, platform=platform))


def extract_playlist(
    source_url: str,
    *,
    settings: Settings | None = None,
    max_items: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> AvExtractResult:
    """Flat-scan a channel/playlist URL → metadata entries (no download)."""
    settings = settings or get_settings()
    if not settings.ytdlp_active:
        raise YtdlpError("未启用音视频采集：请在 .env 设置 ENABLE_YTDLP=true")
    root = _resolve_root(settings)
    if not root.is_dir():
        raise YtdlpError("YTDLP_PATH 未配置或不存在。请执行 bagel setup-ytdlp。")

    platform, http_url = parse_av_source_url(source_url)
    limit = max_items if max_items is not None else settings.av_max_items_per_source
    timeout = max(30, int(settings.av_scan_timeout_sec or 120))
    proc = _run_with_cookie_attempts(
        [
            "--flat-playlist",
            "--dump-single-json",
            "--playlist-end",
            str(max(1, limit)),
            "--no-download",
            "--skip-download",
            http_url,
        ],
        settings=settings,
        root=root,
        platform=platform,
        timeout=timeout,
        on_progress=on_progress,
        show_progress=False,
    )

    entries: list[AvEntry] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("_type") == "playlist" and isinstance(row.get("entries"), list):
            for child in row["entries"]:
                if isinstance(child, dict):
                    ent = _row_to_entry(child, default_platform=platform)
                    if ent:
                        entries.append(ent)
            continue
        ent = _row_to_entry(row, default_platform=platform)
        if ent:
            entries.append(ent)

    return AvExtractResult(entries=entries)


def extract_single(
    url: str,
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> AvEntry:
    settings = settings or get_settings()
    root = _resolve_root(settings)
    platform = _platform_from_url(url)
    proc = _run_with_cookie_attempts(
        ["--dump-single-json", "--no-download", "--skip-download", url],
        settings=settings,
        root=root,
        platform=platform,
        timeout=max(30, settings.av_scan_timeout_sec),
        on_progress=on_progress,
        show_progress=False,
    )
    row = json.loads(proc.stdout.strip().splitlines()[-1])
    ent = _row_to_entry(row, default_platform=platform)
    if not ent:
        raise YtdlpError("无法解析 yt-dlp 输出")
    return ent


def download_entry(
    url: str,
    *,
    out_dir: Path,
    settings: Settings | None = None,
    audio_only: bool | None = None,
    item_id: str | None = None,
    include_subtitles: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Download media file(s) for a single URL (user-triggered on /av detail)."""
    settings = settings or get_settings()
    root = _resolve_root(settings)
    # yt-dlp runs with cwd=checkout; relative -o paths would land under third_party/yt-dlp/.
    out_dir = _absolute_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Short stable name — long Chinese titles + special quotes break Windows pickups.
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "", (item_id or "media"))[:36] or "media"
    template = str(out_dir / f"{stem}.%(ext)s")
    want_audio = audio_only if audio_only is not None else bool(settings.av_default_audio_only)
    extra = ["-o", template, "--no-overwrites", "--restrict-filenames"]
    if want_audio:
        # Keep source video when extracting audio so UI can still offer local play if needed.
        extra.extend(["-x", "--audio-format", "m4a", "-k"])
    else:
        extra.extend(
            [
                "-f",
                f"bestvideo[height<={settings.av_max_height}]+bestaudio/best",
                "--merge-output-format",
                "mp4",
            ]
        )
    if include_subtitles and settings.av_write_subtitles:
        langs = (settings.av_subtitle_langs or "zh,en").replace(" ", "")
        extra.extend(["--write-subs", "--write-auto-subs", "--sub-langs", langs, "--convert-subs", "vtt"])
    extra.append(url)
    if on_progress:
        on_progress(current=15, total=100, message=f"开始下载 {url[:80]}…", percent=15.0)
    try:
        _run_with_cookie_attempts(
            extra,
            settings=settings,
            root=root,
            platform=_platform_from_url(url),
            timeout=3600,
            on_progress=on_progress,
            show_progress=True,
        )
    except YtdlpError as exc:
        err = exc.message
        logger.warning("yt-dlp download failed: %s", err[:300])
        if re.search(r"drm|encrypted|premium only", err, re.I):
            return {"status": "skipped_drm", "error": err}
        return {"status": "failed", "error": err}

    media_files = _list_media_files(out_dir, prefer_audio=want_audio)
    subs = [
        f
        for f in out_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".vtt", ".srt"}
    ]
    if not media_files:
        return {
            "status": "failed",
            "error": (
                f"下载完成但未找到媒体文件（目录 {display_path_safe(out_dir)}）。"
                "若开启了仅音频，请确认 ffmpeg 可用；或将 AV_DEFAULT_AUDIO_ONLY=false 保留视频。"
            ),
        }
    main = media_files[0]
    from bagel.pipeline.paths import display_path

    rel = display_path(str(main))
    if on_progress:
        on_progress(current=100, total=100, message=f"已保存 {main.name}", percent=100.0)
    return {
        "status": "done",
        "local_path": rel,
        "format": main.suffix.lstrip(".").lower(),
        "file_size_bytes": main.stat().st_size,
        "subtitle_path": display_path(str(subs[0])) if subs else None,
        "item_id": item_id,
        "audio_only": want_audio,
    }


def _absolute_out_dir(out_dir: Path) -> Path:
    """Resolve output dir against Bagel CWD (never yt-dlp checkout)."""
    path = Path(out_dir)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    return path


def display_path_safe(path: Path | str) -> str:
    try:
        from bagel.pipeline.paths import display_path

        return display_path(str(path))
    except Exception:
        return str(path)


_MEDIA_EXTS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4a",
        ".mp3",
        ".aac",
        ".opus",
        ".ogg",
        ".wav",
        ".flac",
        ".m4v",
        ".flv",
    }
)
_SKIP_EXTS = frozenset({".vtt", ".srt", ".json", ".jpg", ".jpeg", ".png", ".webp", ".ytdl", ".part", ".temp"})


def _list_media_files(out_dir: Path, *, prefer_audio: bool) -> list[Path]:
    if not out_dir.is_dir():
        return []
    files = [
        f
        for f in out_dir.iterdir()
        if f.is_file()
        and f.suffix.lower() not in _SKIP_EXTS
        and (f.suffix.lower() in _MEDIA_EXTS or f.stat().st_size > 0)
    ]
    audio_exts = {".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".flac"}
    video_exts = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv"}

    def _rank(p: Path) -> tuple[int, float, str]:
        ext = p.suffix.lower()
        if prefer_audio:
            kind = 0 if ext in audio_exts else 1
        else:
            kind = 0 if ext in video_exts else 1
        try:
            mtime = -p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (kind, mtime, p.name)

    return sorted(files, key=_rank)


def extract_subtitles_only(
    url: str,
    *,
    out_dir: Path,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fetch subtitles / auto-captions only — no media download (lightweight)."""
    settings = settings or get_settings()
    root = _resolve_root(settings)
    platform = _platform_from_url(url)
    out_dir = _absolute_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "subs.%(ext)s")
    langs = (settings.av_subtitle_langs or "zh,en").replace(" ", "")
    lang_attempts = [langs]
    if langs != "all":
        lang_attempts.append("all")

    last_err: str | None = None
    for attempt_langs in lang_attempts:
        try:
            _run_with_cookie_attempts(
                [
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-langs",
                    attempt_langs,
                    "--convert-subs",
                    "vtt",
                    "-o",
                    template,
                    url,
                ],
                settings=settings,
                root=root,
                platform=platform,
                timeout=600,
                on_progress=on_progress,
                show_progress=True,
            )
        except YtdlpError as exc:
            last_err = exc.message
            logger.warning("yt-dlp subtitles failed (%s): %s", attempt_langs, exc.message[:300])
            continue
        subs = sorted(out_dir.glob("*.vtt")) + sorted(out_dir.glob("*.srt"))
        if not subs:
            continue
        from bagel.pipeline.paths import display_path

        text_parts: list[str] = []
        for sub in subs[:3]:
            try:
                raw = sub.read_text(encoding="utf-8", errors="ignore")
                text_parts.append(_vtt_to_plain(raw))
            except OSError:
                continue
        plain = "\n\n".join(p for p in text_parts if p).strip()
        if not plain:
            return {
                "status": "failed",
                "error": "字幕文件为空",
                "reason": "empty_subtitle",
            }
        main = subs[0]
        return {
            "status": "done",
            "subtitle_path": display_path(str(main)),
            "subtitle_text": plain[:50000],
            "file_size_bytes": main.stat().st_size,
            "reason": "subtitle",
            "sub_langs": attempt_langs,
        }

    if last_err:
        return {"status": "failed", "error": last_err, "reason": "ytdlp_error"}
    return {
        "status": "failed",
        "error": "平台未提供可下载字幕轨（抖音常见：画面字是烧录字幕，不是 CC）",
        "reason": "no_subtitle_tracks",
    }


def fetch_entry_description(
    url: str,
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Pull title/description via yt-dlp JSON (no download)."""
    settings = settings or get_settings()
    root = _resolve_root(settings)
    platform = _platform_from_url(url)
    try:
        proc = _run_with_cookie_attempts(
            ["--dump-single-json", "--no-download", "--skip-download", url],
            settings=settings,
            root=root,
            platform=platform,
            timeout=max(60, settings.av_scan_timeout_sec),
            on_progress=on_progress,
            show_progress=False,
        )
    except YtdlpError as exc:
        return {"status": "failed", "error": exc.message}
    try:
        row = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"status": "failed", "error": f"无法解析元数据：{exc}"}
    if not isinstance(row, dict):
        return {"status": "failed", "error": "元数据为空"}
    title = (row.get("title") or row.get("fulltitle") or "").strip()
    desc = (row.get("description") or "").strip()
    # Douyin often puts the caption in title and leaves description empty (or vice versa).
    pieces = [p for p in (desc, title) if p]
    best = max(pieces, key=len) if pieces else ""
    return {
        "status": "done",
        "title": title,
        "description": best[:50000],
        "raw_description": desc[:50000],
        "platform": platform,
        "has_subtitles": bool(row.get("subtitles") or row.get("automatic_captions")),
    }


def find_local_av_media(
    item_id: str,
    *,
    settings: Settings | None = None,
    prefer_audio: bool = False,
) -> Path | None:
    """Return newest local media file for an AV item, if present."""
    settings = settings or get_settings()
    out_dir = _absolute_out_dir(Path(settings.data_dir) / "av" / "files" / str(item_id))
    files = _list_media_files(out_dir, prefer_audio=prefer_audio)
    if not files and not prefer_audio:
        files = _list_media_files(out_dir, prefer_audio=True)
    return files[0] if files else None


def _vtt_to_plain(vtt: str) -> str:
    lines: list[str] = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s or s.startswith("WEBVTT") or "-->" in s or s.isdigit():
            continue
        if s.startswith("NOTE"):
            continue
        lines.append(s)
    return "\n".join(lines)


def _subprocess_env(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    proxy = settings.proxy_url
    if proxy:
        env.setdefault("HTTP_PROXY", proxy)
        env.setdefault("HTTPS_PROXY", proxy)
    ff = (settings.ffmpeg_path or "").strip()
    if ff:
        env["PATH"] = str(Path(ff).parent) + os.pathsep + env.get("PATH", "")
    return env
