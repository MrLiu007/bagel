"""Download paper PDFs and parse via MinerU Cloud / Kimi file-extract (load-balanced)."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from bagel.collectors.papers import download_pdf, resolve_pdf_url_with_fallback
from bagel.domain.enums import ItemType
from bagel.domain.models import IntelItem
from bagel.integrations import kimi_files, mineru
from bagel.pipeline.paths import display_path
from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.paper_parse")

ProgressCallback = Callable[..., None]

_rr_lock = threading.Lock()
_rr_index = 0


def providers_ready(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    order = _provider_order(settings)
    ready: list[str] = []
    for name in order:
        if name == "mineru" and mineru.is_configured(settings):
            ready.append("mineru")
        elif name == "kimi" and kimi_files.is_configured(settings):
            ready.append("kimi")
    return ready


def _provider_order(settings: Settings) -> list[str]:
    raw = (settings.paper_parse_providers or "mineru,kimi").strip()
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or ["mineru", "kimi"]


def _pick_providers(settings: Settings) -> list[str]:
    """Round-robin primary, then failover through remaining ready providers."""
    global _rr_index
    ready = providers_ready(settings)
    if not ready:
        return []
    strategy = (settings.paper_parse_strategy or "round_robin").strip().lower()
    if strategy == "failover" or len(ready) == 1:
        return list(ready)
    with _rr_lock:
        start = _rr_index % len(ready)
        _rr_index += 1
    return ready[start:] + ready[:start]


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enabled": settings.enable_paper_parse,
        "providers_order": _provider_order(settings),
        "providers_ready": providers_ready(settings),
        "strategy": settings.paper_parse_strategy,
        "mineru": mineru.status_dict(settings),
        "kimi": kimi_files.status_dict(settings),
    }


def resolve_and_store_pdf_url(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Probe landing page / Zenodo / Unpaywall and persist pdf_url when found."""
    settings = settings or get_settings()
    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "无效条目 ID"}
    item = session.get(IntelItem, iid)
    if not item or item.item_type != ItemType.PAPER:
        return {"status": "FAILED", "error": "条目不存在或不是论文"}

    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    existing = str(meta.get("pdf_url") or "")
    if existing.startswith("http"):
        return {
            "status": "SUCCESS",
            "pdf_url": existing,
            "skipped": True,
            "hint": "already",
        }

    if on_progress:
        on_progress(message="探测开放 PDF 地址…", percent=20.0)
    pdf_url, hint = resolve_pdf_url_with_fallback(
        page_url=item.url,
        external_id=str(meta.get("external_id") or ""),
        raw=meta.get("raw") if isinstance(meta.get("raw"), dict) else None,
        stored_pdf_url=None,
        settings=settings,
        fetch_remote=True,
    )
    if not pdf_url:
        return {
            "status": "FAILED",
            "error": hint or "未找到开放 PDF",
            "pdf_url": None,
        }
    meta["pdf_url"] = pdf_url
    meta["pdf_resolve"] = {"hint": hint, "status": "ok"}
    item.metadata_ = meta
    session.flush()
    if on_progress:
        on_progress(message=f"已找到 PDF：{pdf_url[:80]}", percent=100.0)
    return {"status": "SUCCESS", "pdf_url": pdf_url, "hint": hint}


def ensure_local_pdf(
    item: IntelItem,
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Download OA PDF into data/papers/files/{id}/paper.pdf if missing."""
    settings = settings or get_settings()
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    pdf_meta = meta.get("pdf") if isinstance(meta.get("pdf"), dict) else {}
    out_dir = Path(settings.data_dir) / "papers" / "files" / str(item.id)
    dest = out_dir / "paper.pdf"

    if pdf_meta.get("status") == "done" and dest.is_file():
        return {
            "status": "done",
            "local_path": display_path(str(dest)),
            "pdf_url": pdf_meta.get("pdf_url"),
            "skipped": True,
        }

    pdf_url, hint = resolve_pdf_url_with_fallback(
        page_url=item.url,
        external_id=str(meta.get("external_id") or ""),
        raw=meta.get("raw") if isinstance(meta.get("raw"), dict) else None,
        stored_pdf_url=str(pdf_meta.get("pdf_url") or meta.get("pdf_url") or "") or None,
        settings=settings,
    )
    if not pdf_url:
        return {
            "status": "failed",
            "error": hint or "无法推导 PDF 地址",
        }

    if on_progress:
        on_progress(message=f"下载 PDF {pdf_url[:80]}…", percent=20.0, log_line=pdf_url)
    try:
        download_pdf(pdf_url, dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("paper.pdf_download_failed url=%s err=%s", pdf_url[:120], exc)
        return {"status": "failed", "error": f"PDF 下载失败：{exc}", "pdf_url": pdf_url}

    return {
        "status": "done",
        "local_path": display_path(str(dest)),
        "pdf_url": pdf_url,
        "file_size_bytes": dest.stat().st_size,
        "abs_path": str(dest),
    }


def parse_local_pdf(
    pdf_path: Path,
    *,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Load-balance across configured parsers; failover on provider errors."""
    settings = settings or get_settings()
    chain = _pick_providers(settings)
    if not chain:
        return {
            "status": "failed",
            "error": (
                "无可用文档解析后端。请在系统设置 → 论文 配置 MinerU（MINERU_API_TOKEN）"
                "和/或 Kimi（KIMI_API_KEY），保存个人配置后重试"
            ),
        }

    errors: list[str] = []
    for i, name in enumerate(chain):
        if on_progress:
            on_progress(
                message=f"文档识别：{name}" + (f"（failover {i}）" if i else "") + "…",
                percent=40.0 + 40.0 * i / max(len(chain), 1),
                log_line=f"parse via {name}",
            )
        try:
            if name == "mineru":
                result = mineru.parse_pdf_file(pdf_path, settings=settings)
            elif name == "kimi":
                result = kimi_files.parse_pdf_file(pdf_path, settings=settings)
            else:
                continue
            result["tried"] = chain[: i + 1]
            return result
        except Exception as exc:  # noqa: BLE001
            msg = getattr(exc, "message", None) or str(exc)
            logger.warning("paper.parse_provider_failed provider=%s err=%s", name, msg[:200])
            errors.append(f"{name}: {msg[:160]}")
            if on_progress:
                on_progress(message=f"{name} 失败，尝试下一个…", log_line=msg[:200])

    return {
        "status": "failed",
        "error": "；".join(errors) or "全部解析后端失败",
        "tried": chain,
    }


def run_download_and_parse_paper(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    on_progress: ProgressCallback | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """User-triggered: download PDF → parse → write markdown into IntelItem.content."""
    settings = settings or get_settings()
    if not settings.enable_paper_parse:
        return {"status": "FAILED", "error": "未启用论文解析：.env 设置 ENABLE_PAPER_PARSE=true"}

    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "无效条目 ID"}

    item = session.get(IntelItem, iid)
    if not item or item.item_type != ItemType.PAPER:
        return {"status": "FAILED", "error": "条目不存在或不是论文"}

    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    parse_meta = meta.get("parse") if isinstance(meta.get("parse"), dict) else {}
    if parse_meta.get("status") == "done" and (item.content or "").strip():
        return {"status": "SUCCESS", "skipped": True, "parse": parse_meta}

    if on_progress:
        on_progress(current=1, total=10, message="准备下载 PDF…", percent=10.0)

    dl = ensure_local_pdf(item, settings=settings, on_progress=on_progress)
    meta["pdf"] = {
        "status": dl.get("status"),
        "local_path": dl.get("local_path"),
        "pdf_url": dl.get("pdf_url"),
        "file_size_bytes": dl.get("file_size_bytes"),
        "error": dl.get("error"),
    }
    item.metadata_ = meta
    session.flush()
    if dl.get("status") != "done":
        return {"status": "FAILED", "error": dl.get("error") or "PDF 下载失败", "pdf": meta["pdf"]}

    abs_path = Path(dl.get("abs_path") or (Path(settings.data_dir) / "papers" / "files" / str(item.id) / "paper.pdf"))
    parsed = parse_local_pdf(abs_path, settings=settings, on_progress=on_progress)
    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    meta["parse"] = {
        "status": parsed.get("status", "failed"),
        "provider": parsed.get("provider"),
        "chars": parsed.get("chars"),
        "tried": parsed.get("tried"),
        "error": parsed.get("error"),
    }
    item.metadata_ = meta
    if parsed.get("status") == "done" and parsed.get("markdown"):
        # Raw evidence = parsed markdown; LLM summaries must not overwrite this field later without care.
        item.content = str(parsed["markdown"])[:200_000]
        session.flush()
        if on_progress:
            on_progress(current=10, total=10, message="论文正文已写入", percent=100.0)
        return {
            "status": "SUCCESS",
            "pdf": meta.get("pdf"),
            "parse": meta["parse"],
            "chars": parsed.get("chars"),
        }

    session.flush()
    return {
        "status": "FAILED",
        "error": parsed.get("error") or "解析失败",
        "pdf": meta.get("pdf"),
        "parse": meta["parse"],
    }
