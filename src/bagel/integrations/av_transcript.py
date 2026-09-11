"""Local AV transcript helpers: soft-sub demux + optional ASR.

yt-dlp only downloads *soft* subtitle tracks from the platform. Burned-in
(hard) captions — common on Douyin — are pixels in the video frames and
cannot be recovered by yt-dlp or by demuxing the local file. For those,
use ASR on the audio track (OpenAI-compatible /audio/transcriptions or
optional faster-whisper).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.av_transcript")

ProgressCallback = Callable[..., None]

_AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".opus", ".webm", ".aac", ".flac", ".ogg"}


def _ffmpeg_bin(settings: Settings) -> str | None:
    ff = (settings.ffmpeg_path or "").strip()
    if ff and Path(ff).exists():
        return ff
    return shutil.which("ffmpeg")


def _ffprobe_bin(settings: Settings) -> str | None:
    ff = _ffmpeg_bin(settings)
    if ff:
        probe = Path(ff).with_name(
            "ffprobe.exe" if Path(ff).suffix.lower() == ".exe" else "ffprobe"
        )
        if probe.exists():
            return str(probe)
    return shutil.which("ffprobe")


def probe_media_streams(path: Path, *, settings: Settings | None = None) -> dict[str, Any]:
    """Return stream summary for a local media file."""
    settings = settings or get_settings()
    probe = _ffprobe_bin(settings)
    if not probe or not path.is_file():
        return {"ok": False, "error": "ffprobe 不可用或文件不存在", "streams": []}
    try:
        proc = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "streams": []}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "ffprobe failed")[:400], "streams": []}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "ffprobe JSON 无效", "streams": []}
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    subs = [s for s in streams if (s.get("codec_type") or "") == "subtitle"]
    return {
        "ok": True,
        "streams": streams,
        "subtitle_streams": subs,
        "has_soft_subs": bool(subs),
        "duration_sec": float((data.get("format") or {}).get("duration") or 0) or None,
    }


def extract_soft_subtitles(
    media_path: Path,
    *,
    out_dir: Path,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Demux soft subtitle tracks from a local container (if any)."""
    settings = settings or get_settings()
    ff = _ffmpeg_bin(settings)
    if not ff:
        return {"status": "failed", "error": "未找到 ffmpeg", "reason": "no_ffmpeg"}
    info = probe_media_streams(media_path, settings=settings)
    if not info.get("has_soft_subs"):
        return {
            "status": "failed",
            "error": "本地文件无独立字幕轨（烧录字幕不会出现在此）",
            "reason": "no_soft_subs",
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_srt = out_dir / f"{media_path.stem}.soft.srt"
    try:
        proc = subprocess.run(
            [
                ff,
                "-y",
                "-i",
                str(media_path),
                "-map",
                "0:s:0",
                "-c:s",
                "srt",
                str(out_srt),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "error": str(exc), "reason": "ffmpeg_error"}
    if proc.returncode != 0 or not out_srt.is_file() or out_srt.stat().st_size < 8:
        return {
            "status": "failed",
            "error": (proc.stderr or "无法抽出字幕轨")[:400],
            "reason": "demux_failed",
        }
    text = _srt_to_plain(out_srt.read_text(encoding="utf-8", errors="ignore"))
    if len(text.strip()) < 4:
        return {"status": "failed", "error": "字幕轨为空", "reason": "empty_subtitle"}
    from bagel.pipeline.paths import display_path

    return {
        "status": "done",
        "subtitle_path": display_path(str(out_srt)),
        "subtitle_text": text[:50000],
        "reason": "soft_sub",
    }


def extract_audio_track(
    media_path: Path,
    *,
    out_path: Path,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Extract a compact mono mp3 for ASR (keeps size under common API limits)."""
    settings = settings or get_settings()
    ff = _ffmpeg_bin(settings)
    if not ff:
        return {"status": "failed", "error": "未找到 ffmpeg", "reason": "no_ffmpeg"}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(120, int(media_path.stat().st_size / (256 * 1024)) + 60)
    try:
        proc = subprocess.run(
            [
                ff,
                "-y",
                "-i",
                str(media_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "error": str(exc), "reason": "ffmpeg_error"}
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size < 32:
        return {
            "status": "failed",
            "error": (proc.stderr or "抽音频失败")[:400],
            "reason": "audio_extract_failed",
        }
    return {"status": "done", "audio_path": str(out_path), "bytes": out_path.stat().st_size}


def transcribe_local_media(
    media_path: Path,
    *,
    work_dir: Path,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """ASR transcript from local video/audio. Requires AV_ASR_ENABLED + backend."""
    settings = settings or get_settings()
    if not settings.av_asr_enabled:
        return {
            "status": "skipped",
            "error": "ASR 未启用（AV_ASR_ENABLED=false）",
            "reason": "asr_off",
        }
    backend = (settings.av_asr_backend or "auto").strip().lower()
    if backend in {"off", "none", "0"}:
        return {"status": "skipped", "error": "ASR backend=off", "reason": "asr_off"}

    if on_progress:
        on_progress(current=4, total=10, message="从本地视频抽取音轨…", percent=40.0)

    audio_path = work_dir / "asr_audio.mp3"
    if media_path.suffix.lower() in _AUDIO_EXTS:
        audio_src = media_path
    else:
        extracted = extract_audio_track(media_path, out_path=audio_path, settings=settings)
        if extracted.get("status") != "done":
            return extracted
        audio_src = Path(str(extracted["audio_path"]))

    if on_progress:
        on_progress(current=6, total=10, message=f"ASR 识别中（{backend}）…", percent=60.0)

    from bagel.integrations.volc_asr import transcribe_volcengine, volc_asr_configured

    if backend == "auto":
        order: list[str] = []
        if volc_asr_configured(settings):
            order.append("volcengine")
        order.extend(["openai", "faster_whisper"])
    elif backend in {"volcengine", "volc", "doubao", "seedasr"}:
        order = ["volcengine"]
    elif backend in {"openai", "whisper_api"}:
        order = ["openai"]
    elif backend in {"faster_whisper", "whisper", "local"}:
        order = ["faster_whisper"]
    else:
        return {
            "status": "failed",
            "error": f"未知 ASR backend: {backend}",
            "reason": "bad_backend",
        }

    errors: list[str] = []
    for name in order:
        if name == "volcengine":
            if not volc_asr_configured(settings):
                errors.append("volcengine: 未配置密钥")
                continue
            result = transcribe_volcengine(
                audio_src, settings=settings, on_progress=on_progress
            )
        elif name == "openai":
            result = _transcribe_openai(audio_src, settings=settings)
        else:
            result = _transcribe_faster_whisper(audio_src, settings=settings)
        if result.get("status") == "done" and (result.get("text") or "").strip():
            result["backend"] = name
            if on_progress:
                on_progress(current=9, total=10, message=f"ASR 完成（{name}）", percent=90.0)
            return result
        errors.append(f"{name}: {result.get('error') or result.get('reason') or 'failed'}")

    return {
        "status": "failed",
        "error": "本地 ASR 失败：" + "；".join(errors)[:500],
        "reason": "asr_failed",
    }


def _transcribe_openai(audio_path: Path, *, settings: Settings) -> dict[str, Any]:
    """OpenAI-compatible /v1/audio/transcriptions (needs provider support)."""
    key = (settings.llm_api_key or "").strip()
    base = (settings.llm_base_url or "").strip().rstrip("/")
    if not key or not base:
        return {
            "status": "failed",
            "error": "未配置 LLM_API_KEY / LLM_BASE_URL，无法调用云端 Whisper",
            "reason": "no_llm",
        }
    if audio_path.stat().st_size > 24 * 1024 * 1024:
        return {
            "status": "failed",
            "error": "音轨超过 24MB，云端 Whisper 受限；可改用 faster-whisper 本地识别",
            "reason": "audio_too_large",
        }
    url = f"{base}/audio/transcriptions"
    model = (settings.av_asr_model or "whisper-1").strip() or "whisper-1"
    language = (settings.av_asr_language or "").strip() or None
    try:
        import httpx
    except ImportError:
        return {"status": "failed", "error": "缺少 httpx", "reason": "no_httpx"}
    data: dict[str, str] = {"model": model, "response_format": "text"}
    if language:
        data["language"] = language
    try:
        with audio_path.open("rb") as fh:
            with httpx.Client(timeout=max(120, settings.llm_timeout_seconds)) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    data=data,
                    files={"file": (audio_path.name, fh, "audio/mpeg")},
                )
    except httpx.HTTPError as exc:
        return {"status": "failed", "error": f"Whisper API 网络错误：{exc}", "reason": "network"}
    if resp.status_code >= 400:
        return {
            "status": "failed",
            "error": f"Whisper API HTTP {resp.status_code}: {resp.text[:300]}",
            "reason": "api_error",
        }
    text = (resp.text or "").strip()
    if not text:
        return {"status": "failed", "error": "Whisper 返回空文本", "reason": "empty"}
    return {"status": "done", "text": text[:50000], "reason": "asr_openai"}


def _transcribe_faster_whisper(audio_path: Path, *, settings: Settings) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return {
            "status": "failed",
            "error": "未安装 faster-whisper（可选：uv pip install faster-whisper）",
            "reason": "no_faster_whisper",
        }
    model_name = (settings.av_asr_model or "small").strip() or "small"
    if model_name in {"whisper-1", "gpt-4o-transcribe"}:
        model_name = "small"
    language = (settings.av_asr_language or "").strip() or None
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments if (seg.text or "").strip()]
    except Exception as exc:  # noqa: BLE001 — surface any runtime/model error
        logger.warning("faster-whisper failed: %s", exc)
        return {
            "status": "failed",
            "error": f"faster-whisper 失败：{exc}",
            "reason": "whisper_error",
        }
    text = "\n".join(parts).strip()
    if not text:
        return {"status": "failed", "error": "识别结果为空", "reason": "empty"}
    return {"status": "done", "text": text[:50000], "reason": "asr_local"}


def _srt_to_plain(srt: str) -> str:
    lines: list[str] = []
    for line in srt.splitlines():
        s = line.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        lines.append(s)
    return "\n".join(lines)


def burned_in_caption_note() -> str:
    """User-facing note used in UI / errors."""
    return (
        "图中底部白字多为烧录字幕（像素画在画面上）。"
        "yt-dlp 与本地容器均无独立字幕轨时可抽不出来；"
        "需对本地音轨做 ASR（语音识别）才能得到口播文稿。"
    )
