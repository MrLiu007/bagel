"""MinerU Cloud document parse adapter (HTTP API — no local clone).

Docs: https://mineru.net/apiManage/docs
Uses local file upload (batch file-urls) so overseas PDF hosts don't time out.
"""

from __future__ import annotations

import logging
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.mineru")

BASE = "https://mineru.net"
AGENT_BASE = f"{BASE}/api/v1/agent"


class MineruError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.enable_mineru and (settings.mineru_api_token or "").strip())


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": settings.enable_mineru,
        "token_configured": bool((settings.mineru_api_token or "").strip()),
        "model_version": settings.mineru_model_version or "vlm",
        "ready": is_configured(settings),
    }


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def _client(settings: Settings, timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        proxy=settings.proxy_url or None,
        follow_redirects=True,
    )


def parse_pdf_file(
    pdf_path: Path,
    *,
    settings: Settings | None = None,
    poll_timeout_sec: int | None = None,
) -> dict[str, Any]:
    """Upload local PDF via MinerU batch file-urls API and return markdown text."""
    settings = settings or get_settings()
    if not is_configured(settings):
        raise MineruError("未配置 MinerU：请在 .env 设置 ENABLE_MINERU=true 与 MINERU_API_TOKEN")
    path = Path(pdf_path)
    if not path.is_file():
        raise MineruError(f"PDF 不存在：{path.name}")

    token = (settings.mineru_api_token or "").strip()
    model = (settings.mineru_model_version or "vlm").strip() or "vlm"
    timeout = poll_timeout_sec or int(settings.paper_parse_timeout_sec or 300)

    with _client(settings) as client:
        apply = client.post(
            f"{BASE}/api/v4/file-urls/batch",
            headers=_headers(token),
            json={
                "files": [{"name": path.name, "data_id": path.stem[:64]}],
                "model_version": model,
            },
        )
        apply.raise_for_status()
        body = apply.json()
        if int(body.get("code") or 0) != 0:
            raise MineruError(body.get("msg") or f"MinerU 申请上传失败：{body}")
        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or data.get("urls") or []
        if not batch_id or not urls:
            raise MineruError("MinerU 未返回 batch_id / file_urls")

        upload_url = urls[0]
        with path.open("rb") as fh:
            put = client.put(upload_url, content=fh.read())
        if put.status_code not in (200, 201):
            raise MineruError(f"MinerU 上传失败 HTTP {put.status_code}")

        logger.info("mineru.uploaded batch_id=%s file=%s", batch_id, path.name)
        deadline = time.monotonic() + timeout
        md_text = ""
        full_zip_url = ""
        while time.monotonic() < deadline:
            time.sleep(3)
            poll = client.get(
                f"{BASE}/api/v4/extract-results/batch/{batch_id}",
                headers=_headers(token),
            )
            poll.raise_for_status()
            pbody = poll.json()
            pdata = pbody.get("data") or {}
            results = pdata.get("extract_result") or pdata.get("extract_results") or []
            if not results and isinstance(pdata.get("result"), list):
                results = pdata["result"]
            if not results:
                state = (pdata.get("state") or pdata.get("status") or "").lower()
                if state in {"failed", "error"}:
                    raise MineruError(pdata.get("err_msg") or "MinerU 解析失败")
                continue
            row = results[0] if isinstance(results[0], dict) else {}
            state = (row.get("state") or row.get("status") or "").lower()
            if state in {"failed", "error"}:
                raise MineruError(row.get("err_msg") or row.get("error") or "MinerU 解析失败")
            if state not in {"done", "success", "completed"}:
                continue
            full_zip_url = row.get("full_zip_url") or row.get("zip_url") or ""
            md_url = row.get("md_url") or row.get("markdown_url") or ""
            if md_url:
                md_resp = client.get(md_url)
                md_resp.raise_for_status()
                md_text = md_resp.text
            elif full_zip_url:
                md_text = _markdown_from_zip(client.get(full_zip_url).content)
            break
        else:
            raise MineruError(f"MinerU 轮询超时（{timeout}s）batch_id={batch_id}")

    if not (md_text or "").strip():
        raise MineruError("MinerU 完成但未返回 Markdown")
    return {
        "provider": "mineru",
        "status": "done",
        "markdown": md_text.strip(),
        "batch_id": batch_id,
        "zip_url": full_zip_url or None,
        "chars": len(md_text),
    }


def _markdown_from_zip(blob: bytes) -> str:
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".md")]
        if not names:
            names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not names:
            return ""
        # Prefer full.md / auto.md style names
        names.sort(key=lambda n: (0 if "full" in n.lower() or "auto" in n.lower() else 1, len(n)))
        return zf.read(names[0]).decode("utf-8", errors="ignore")
