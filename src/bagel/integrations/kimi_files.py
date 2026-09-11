"""Kimi (Moonshot) file-extract adapter for PDF → text.

Docs: https://platform.kimi.com/docs/api/files-upload
Uses OpenAI-compatible Files API (no SDK dependency).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.kimi_files")


class KimiFilesError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _base_url(settings: Settings) -> str:
    explicit = (settings.kimi_files_base_url or "").strip().rstrip("/")
    if explicit:
        return explicit
    llm = (settings.llm_base_url or "").strip().rstrip("/")
    if "moonshot" in llm.lower() or "kimi" in llm.lower():
        return llm
    return "https://api.moonshot.cn/v1"


def _api_key(settings: Settings) -> str:
    key = (settings.kimi_api_key or "").strip()
    if key:
        return key
    # Reuse Moonshot LLM key when provider is moonshot/kimi.
    provider = (settings.llm_provider or "").lower()
    if provider in {"moonshot", "kimi"} or "moonshot" in (settings.llm_base_url or "").lower():
        return (settings.llm_api_key or "").strip()
    return ""


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.enable_kimi_files and _api_key(settings))


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": settings.enable_kimi_files,
        "key_configured": bool(_api_key(settings)),
        "base_url": _base_url(settings),
        "ready": is_configured(settings),
    }


def parse_pdf_file(
    pdf_path: Path,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Upload PDF with purpose=file-extract and retrieve extracted text."""
    settings = settings or get_settings()
    if not is_configured(settings):
        raise KimiFilesError(
            "未配置 Kimi 文件解析：设置 ENABLE_KIMI_FILES=true 与 KIMI_API_KEY"
            "（或 LLM_PROVIDER=moonshot 且配置 LLM_API_KEY）"
        )
    path = Path(pdf_path)
    if not path.is_file():
        raise KimiFilesError(f"PDF 不存在：{path.name}")

    key = _api_key(settings)
    base = _base_url(settings)
    timeout = float(settings.paper_parse_timeout_sec or 300)

    with httpx.Client(timeout=timeout, proxy=settings.proxy_url or None, follow_redirects=True) as client:
        with path.open("rb") as fh:
            up = client.post(
                f"{base}/files",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (path.name, fh, "application/pdf")},
                data={"purpose": "file-extract"},
            )
        if up.status_code >= 400:
            raise KimiFilesError(f"Kimi 上传失败 HTTP {up.status_code}: {up.text[:240]}")
        meta = up.json()
        file_id = meta.get("id")
        if not file_id:
            raise KimiFilesError(f"Kimi 上传未返回 file id：{meta}")

        logger.info("kimi.uploaded file_id=%s name=%s", file_id, path.name)
        content = client.get(
            f"{base}/files/{file_id}/content",
            headers={"Authorization": f"Bearer {key}"},
        )
        if content.status_code >= 400:
            # Older API variant
            content = client.get(
                f"{base}/files/{file_id}/content",
                headers={"Authorization": f"Bearer {key}", "Accept": "text/plain"},
            )
        if content.status_code >= 400:
            raise KimiFilesError(
                f"Kimi 获取文件内容失败 HTTP {content.status_code}: {content.text[:240]}"
            )
        text = content.text

        # Best-effort cleanup to free quota.
        try:
            client.delete(
                f"{base}/files/{file_id}",
                headers={"Authorization": f"Bearer {key}"},
            )
        except Exception:  # noqa: BLE001
            logger.debug("kimi.delete_skipped file_id=%s", file_id)

    if not (text or "").strip():
        raise KimiFilesError("Kimi 返回空文本")
    return {
        "provider": "kimi",
        "status": "done",
        "markdown": text.strip(),
        "file_id": file_id,
        "chars": len(text),
    }
