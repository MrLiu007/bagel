"""Volcengine openspeech 录音文件识别（豆包语音 AUC）。

Endpoints (openspeech.bytedance.com):
- 标准版提交: /api/v3/auc/bigmodel/submit
- 标准版查询: /api/v3/auc/bigmodel/query
- 极速版:     /api/v3/auc/bigmodel/recognize/flash

Docs:
- https://docs.volcengine.com/docs/6561/1354868  (submit)
- https://docs.volcengine.com/docs/6561/2606792  (query)
- https://docs.volcengine.com/docs/6561/1631584  (flash)

Auth（豆包语音控制台，二选一）:
- 旧版: X-Api-App-Key (APP ID) + X-Api-Access-Key (Access Token)
- 新版: X-Api-Key
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.volc_asr")

ProgressCallback = Callable[..., None]

SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
FLASH_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"

STATUS_OK = "20000000"
STATUS_PROCESSING = "20000001"
STATUS_QUEUED = "20000002"
STATUS_SILENT = "20000003"

_RETRYABLE_CODES = {"55000031", "55000000"}
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def volc_asr_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    api_key = (s.volc_asr_api_key or "").strip()
    app_id = (s.volc_asr_app_id or "").strip()
    access = (s.volc_asr_access_key or "").strip()
    return bool(api_key or (app_id and access))


def _auth_headers(
    settings: Settings,
    request_id: str,
    *,
    resource_id: str,
    with_sequence: bool = False,
) -> dict[str, str]:
    """Build openspeech headers. Prefer APP ID + Access Token when both set."""
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
    }
    if with_sequence:
        headers["X-Api-Sequence"] = "-1"

    app_id = (settings.volc_asr_app_id or "").strip()
    access = (settings.volc_asr_access_key or "").strip()
    api_key = (settings.volc_asr_api_key or "").strip()

    if app_id and access:
        headers["X-Api-App-Key"] = app_id
        headers["X-Api-Access-Key"] = access
    elif api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _request_uid(settings: Settings) -> str:
    app_id = (settings.volc_asr_app_id or "").strip()
    if app_id:
        return app_id
    api_key = (settings.volc_asr_api_key or "").strip()
    if api_key:
        return api_key[:64]
    return (settings.volc_asr_uid or "bagel").strip() or "bagel"


def _language_code(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower().replace("_", "-")
    if low in {"zh", "zh-cn", "cn", "chinese"}:
        return "zh-CN"
    if low in {"en", "en-us", "english"}:
        return "en-US"
    if low in {"yue", "yue-cn", "cantonese"}:
        return "yue-CN"
    if "-" in s and len(s) <= 12:
        return s
    return None


def _audio_format(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in {"mp3", "wav", "ogg", "raw"}:
        return ext
    return "mp3"


def _status_code(resp: httpx.Response) -> str:
    return (resp.headers.get("X-Api-Status-Code") or resp.headers.get("x-api-status-code") or "").strip()


def _status_message(resp: httpx.Response) -> str:
    return (resp.headers.get("X-Api-Message") or resp.headers.get("x-api-message") or "").strip()


def _log_id(resp: httpx.Response) -> str:
    return (resp.headers.get("X-Tt-Logid") or resp.headers.get("x-tt-logid") or "").strip()


def _extract_text(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    result = body.get("result")
    if isinstance(result, dict):
        text = (result.get("text") or "").strip()
        if text:
            return text
        utts = result.get("utterances")
        if isinstance(utts, list):
            parts = [(u.get("text") or "").strip() for u in utts if isinstance(u, dict)]
            return "\n".join(p for p in parts if p)
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            return (first.get("text") or "").strip()
    return (body.get("text") or "").strip()


def _build_audio_payload(audio_path: Path, settings: Settings) -> dict[str, Any]:
    raw = audio_path.read_bytes()
    audio: dict[str, Any] = {
        "data": base64.b64encode(raw).decode("ascii"),
        "format": _audio_format(audio_path),
    }
    lang = _language_code(settings.av_asr_language or settings.volc_asr_language or "")
    if lang:
        audio["language"] = lang
    return audio


def _request_body(audio_path: Path, settings: Settings) -> dict[str, Any]:
    return {
        "user": {"uid": _request_uid(settings)},
        "audio": _build_audio_payload(audio_path, settings),
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
        },
    }


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    retries: int,
) -> httpx.Response:
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None
    for attempt in range(max(1, retries)):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
            last_resp = resp
            code = _status_code(resp)
            if resp.status_code in _RETRYABLE_HTTP or code in _RETRYABLE_CODES:
                wait = min(30.0, 1.5 * (2**attempt))
                logger.warning(
                    "openspeech ASR retryable http=%s code=%s logid=%s attempt=%s wait=%.1fs",
                    resp.status_code,
                    code,
                    _log_id(resp),
                    attempt + 1,
                    wait,
                )
                time.sleep(wait)
                continue
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            wait = min(30.0, 1.5 * (2**attempt))
            logger.warning("openspeech ASR network error: %s attempt=%s", exc, attempt + 1)
            time.sleep(wait)
    if last_resp is not None:
        return last_resp
    if last_exc:
        raise last_exc
    raise RuntimeError("openspeech ASR retries exhausted")


def transcribe_volcengine(
    audio_path: Path,
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Transcribe a local audio file via openspeech AUC (flash and/or submit/query)."""
    settings = settings or get_settings()
    if not volc_asr_configured(settings):
        return {
            "status": "failed",
            "error": (
                "未配置 openspeech ASR：请填 VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_KEY"
                "（豆包语音旧版），或 VOLC_ASR_API_KEY（新版）"
            ),
            "reason": "no_volc_creds",
        }
    if not audio_path.is_file():
        return {"status": "failed", "error": "音轨文件不存在", "reason": "no_file"}

    size = audio_path.stat().st_size
    max_bytes = max(1, int(settings.volc_asr_max_file_mb)) * 1024 * 1024
    if size > max_bytes:
        return {
            "status": "failed",
            "error": f"音轨过大（{size // (1024 * 1024)}MB > {settings.volc_asr_max_file_mb}MB）",
            "reason": "audio_too_large",
        }
    if size < 64:
        return {"status": "failed", "error": "音轨过小或为空", "reason": "empty_audio"}

    mode = (settings.volc_asr_mode or "auto").strip().lower()
    use_flash = mode == "flash" or (
        mode == "auto" and size <= max(1, int(settings.volc_asr_flash_max_mb)) * 1024 * 1024
    )

    errors: list[str] = []
    if use_flash and mode != "async":
        if on_progress:
            on_progress(current=6, total=10, message="openspeech 极速识别…", percent=62.0)
        flash = _recognize_flash(audio_path, settings=settings)
        if flash.get("status") == "done":
            return flash
        errors.append(f"flash: {flash.get('error') or flash.get('reason')}")
        if mode == "flash":
            return flash

    if on_progress:
        on_progress(current=6, total=10, message="openspeech 提交任务…", percent=55.0)
    async_result = _recognize_async(audio_path, settings=settings, on_progress=on_progress)
    if async_result.get("status") == "done":
        return async_result
    errors.append(f"async: {async_result.get('error') or async_result.get('reason')}")
    return {
        "status": "failed",
        "error": "openspeech ASR 失败：" + "；".join(errors)[:600],
        "reason": str(async_result.get("reason") or "volc_failed"),
        "detail": {k: async_result.get(k) for k in ("error", "reason", "request_id", "logid")},
    }


def _recognize_flash(audio_path: Path, *, settings: Settings) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    resource = (settings.volc_asr_flash_resource_id or "volc.bigasr.auc_turbo").strip()
    headers = _auth_headers(settings, request_id, resource_id=resource, with_sequence=True)
    try:
        resp = _post_json(
            FLASH_URL,
            headers=headers,
            payload=_request_body(audio_path, settings),
            timeout=max(60.0, float(settings.volc_asr_http_timeout_sec)),
            retries=max(1, int(settings.volc_asr_max_retries)),
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"极速版网络错误：{exc}", "reason": "network"}

    code = _status_code(resp)
    logid = _log_id(resp)
    if code != STATUS_OK:
        return {
            "status": "failed",
            "error": f"极速版失败 code={code} msg={_status_message(resp)} logid={logid}",
            "reason": f"volc_{code or resp.status_code}",
        }
    try:
        body = resp.json() if resp.content else {}
    except Exception:  # noqa: BLE001
        body = {}
    text = _extract_text(body)
    if not text:
        return {
            "status": "failed",
            "error": f"极速版返回空文本 logid={logid}",
            "reason": "empty",
        }
    return {
        "status": "done",
        "text": text[:50000],
        "reason": "asr_volc_flash",
        "request_id": request_id,
        "logid": logid,
    }


def _recognize_async(
    audio_path: Path,
    *,
    settings: Settings,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    resource = (settings.volc_asr_resource_id or "volc.seedasr.auc").strip()
    headers = _auth_headers(settings, request_id, resource_id=resource, with_sequence=True)
    try:
        submit = _post_json(
            SUBMIT_URL,
            headers=headers,
            payload=_request_body(audio_path, settings),
            timeout=max(60.0, float(settings.volc_asr_http_timeout_sec)),
            retries=max(1, int(settings.volc_asr_max_retries)),
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"提交失败：{exc}", "reason": "network"}

    code = _status_code(submit)
    logid = _log_id(submit)
    if code != STATUS_OK:
        return {
            "status": "failed",
            "error": f"提交失败 code={code} msg={_status_message(submit)} logid={logid}",
            "reason": f"volc_{code or submit.status_code}",
        }

    poll_interval = max(1.0, float(settings.volc_asr_poll_interval_sec))
    poll_timeout = max(30.0, float(settings.volc_asr_poll_timeout_sec))
    deadline = time.monotonic() + poll_timeout
    query_headers = _auth_headers(settings, request_id, resource_id=resource, with_sequence=False)
    if logid:
        query_headers["X-Tt-Logid"] = logid

    polls = 0
    while time.monotonic() < deadline:
        polls += 1
        if on_progress:
            elapsed = int(poll_timeout - (deadline - time.monotonic()))
            on_progress(
                current=min(8, 5 + polls // 3),
                total=10,
                message=f"openspeech 轮询中… ({elapsed}s)",
                percent=min(88.0, 55.0 + polls * 1.5),
            )
        try:
            with httpx.Client(timeout=max(30.0, float(settings.volc_asr_http_timeout_sec))) as client:
                resp = client.post(QUERY_URL, headers=query_headers, json={})
        except httpx.HTTPError as exc:
            logger.warning("openspeech ASR query network: %s", exc)
            time.sleep(poll_interval)
            continue

        qcode = _status_code(resp)
        qlog = _log_id(resp) or logid
        if qcode in {STATUS_PROCESSING, STATUS_QUEUED, ""}:
            time.sleep(poll_interval)
            continue
        if qcode == STATUS_SILENT:
            return {
                "status": "failed",
                "error": f"静音音频（无有效人声）logid={qlog}",
                "reason": "silent",
            }
        if qcode != STATUS_OK:
            if qcode in _RETRYABLE_CODES:
                time.sleep(min(10.0, poll_interval * 2))
                continue
            return {
                "status": "failed",
                "error": f"查询失败 code={qcode} msg={_status_message(resp)} logid={qlog}",
                "reason": f"volc_{qcode or resp.status_code}",
            }
        try:
            body = resp.json() if resp.content else {}
        except Exception:  # noqa: BLE001
            body = {}
        text = _extract_text(body)
        if not text:
            return {
                "status": "failed",
                "error": f"识别结果为空 logid={qlog}",
                "reason": "empty",
            }
        return {
            "status": "done",
            "text": text[:50000],
            "reason": "asr_volc_async",
            "request_id": request_id,
            "logid": qlog,
            "polls": polls,
        }

    return {
        "status": "failed",
        "error": f"openspeech ASR 轮询超时（{int(poll_timeout)}s）request_id={request_id}",
        "reason": "timeout",
    }
