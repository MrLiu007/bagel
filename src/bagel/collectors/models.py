"""Model hub collectors — Hugging Face Hub + ModelScope (魔搭)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from bagel.settings import get_settings

logger = logging.getLogger(__name__)
USER_AGENT = "Bagel/0.3 (model-collector; +https://github.com/MrLiu007/bagel)"

# Community codes used for UI filter tabs (metadata.community / platform).
COMMUNITY_HUGGINGFACE = "huggingface"
COMMUNITY_MODELSCOPE = "modelscope"

COMMUNITY_LABELS: dict[str, str] = {
    COMMUNITY_HUGGINGFACE: "Hugging Face",
    COMMUNITY_MODELSCOPE: "ModelScope 魔搭",
}


@dataclass
class ModelRecord:
    title: str
    url: str
    summary: str
    author: str
    published_at: datetime | None
    community: str
    external_id: str
    model_id: str
    downloads: int = 0
    likes: int = 0
    pipeline_tag: str = ""
    tags: list[str] | None = None
    raw: dict[str, Any] | None = None


def _client(*, use_proxy: bool = True, timeout: float = 45.0) -> httpx.Client:
    settings = get_settings()
    proxy = (settings.proxy_url or None) if use_proxy else None
    return httpx.Client(
        timeout=timeout,
        proxy=proxy,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def _parse_date(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # ModelScope often uses unix seconds.
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def fetch_huggingface_models(
    *,
    sort: str = "lastModified",
    search: str = "",
    pipeline_tag: str = "",
    limit: int = 30,
) -> list[ModelRecord]:
    """List / search models on Hugging Face Hub (public API, no token required)."""
    params: list[str] = [
        f"sort={quote_plus(sort)}",
        "direction=-1",
        f"limit={max(1, min(limit, 50))}",
    ]
    if search:
        params.append(f"search={quote_plus(search)}")
    if pipeline_tag:
        params.append(f"pipeline_tag={quote_plus(pipeline_tag)}")
    url = "https://huggingface.co/api/models?" + "&".join(params)
    with _client(use_proxy=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        data = data.get("models") or data.get("items") or []
    out: list[ModelRecord] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        model_id = (row.get("modelId") or row.get("id") or "").strip()
        if not model_id:
            continue
        author = model_id.split("/", 1)[0] if "/" in model_id else ""
        pipeline = (row.get("pipeline_tag") or "").strip()
        tags = [str(t) for t in (row.get("tags") or []) if t][:12]
        downloads = int(row.get("downloads") or 0)
        likes = int(row.get("likes") or 0)
        summary_parts = []
        if pipeline:
            summary_parts.append(f"任务：{pipeline}")
        if downloads:
            summary_parts.append(f"下载 {downloads:,}")
        if likes:
            summary_parts.append(f"likes {likes:,}")
        if tags:
            summary_parts.append("标签：" + ", ".join(tags[:6]))
        out.append(
            ModelRecord(
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                summary=" · ".join(summary_parts) or model_id,
                author=author[:255],
                published_at=_parse_date(row.get("lastModified") or row.get("createdAt")),
                community=COMMUNITY_HUGGINGFACE,
                external_id=f"hf:{model_id}",
                model_id=model_id,
                downloads=downloads,
                likes=likes,
                pipeline_tag=pipeline,
                tags=tags,
                raw=row,
            )
        )
    return out


def fetch_modelscope_models(
    *,
    sort: str = "GmtModified",
    search: str = "",
    limit: int = 30,
) -> list[ModelRecord]:
    """List models on ModelScope via the public dolphin API (no token)."""
    # SortBy values used by modelscope.cn web (RSSHub-compatible).
    sort_map = {
        "modified": "GmtModified",
        "gmtmodified": "GmtModified",
        "downloads": "Downloads",
        "stars": "Stars",
        "likes": "Stars",
        "trending": "GmtModified",
    }
    sort_key = sort_map.get(sort.lower().replace("_", ""), sort if sort else "GmtModified")
    body = {
        "PageSize": max(1, min(limit, 50)),
        "PageNumber": 1,
        "SortBy": sort_key,
        "Target": (search or "").strip(),
        "SingleCriterion": [],
    }
    url = "https://www.modelscope.cn/api/v1/dolphin/models"
    with _client(use_proxy=False) as client:
        resp = client.put(url, json=body)
        resp.raise_for_status()
        payload = resp.json()
    models = (
        (((payload or {}).get("Data") or {}).get("Model") or {}).get("Models")
        or ((payload or {}).get("Data") or {}).get("Models")
        or []
    )
    out: list[ModelRecord] = []
    for row in models:
        if not isinstance(row, dict):
            continue
        path = (row.get("Path") or row.get("path") or "").strip()
        name = (row.get("Name") or row.get("name") or "").strip()
        model_id = f"{path}/{name}" if path and name else (path or name)
        if not model_id:
            continue
        chinese = (row.get("ChineseName") or row.get("chinese_name") or "").strip()
        title = chinese or model_id
        desc = (row.get("Description") or row.get("description") or "").strip()
        org = row.get("Organization") or {}
        author = ""
        if isinstance(org, dict):
            author = (org.get("FullName") or org.get("Name") or path or "")[:255]
        else:
            author = (path or "")[:255]
        tasks = row.get("Tasks") or []
        task_names: list[str] = []
        for t in tasks:
            if isinstance(t, dict):
                label = (t.get("ChineseName") or t.get("Name") or "").strip()
                if label:
                    task_names.append(label)
            elif t:
                task_names.append(str(t))
        tags = [str(t) for t in (row.get("Tags") or []) if t][:12]
        downloads = int(row.get("Downloads") or row.get("downloads") or 0)
        likes = int(row.get("Stars") or row.get("likes") or 0)
        summary_parts = []
        if desc:
            summary_parts.append(desc[:400])
        if task_names:
            summary_parts.append("任务：" + ", ".join(task_names[:4]))
        if downloads:
            summary_parts.append(f"下载 {downloads:,}")
        if likes:
            summary_parts.append(f"收藏 {likes:,}")
        published = _parse_date(
            row.get("GmtModified")
            or row.get("CreatedTime")
            or row.get("gmt_modified")
            or row.get("created_time")
        )
        out.append(
            ModelRecord(
                title=title[:500],
                url=f"https://www.modelscope.cn/models/{model_id}",
                summary=" · ".join(summary_parts)[:2000] or model_id,
                author=author,
                published_at=published,
                community=COMMUNITY_MODELSCOPE,
                external_id=f"ms:{model_id}",
                model_id=model_id,
                downloads=downloads,
                likes=likes,
                pipeline_tag=task_names[0] if task_names else "",
                tags=tags or task_names,
                raw=row,
            )
        )
    return out


def fetch_from_source(name: str, url: str) -> list[ModelRecord]:
    """Dispatch by URL scheme used in seed & settings.

    Schemes:
      hf:models
      hf:models:downloads
      hf:models:pipeline:text-generation
      hf:models:search:qwen
      ms:models
      ms:models:downloads
      ms:models:search:qwen
      modelscope:… (alias of ms:)
    """
    raw = (url or "").strip()
    lower = raw.lower()
    label = (name or "").lower()

    if lower.startswith("hf:") or "huggingface.co" in lower or "hugging face" in label:
        return _dispatch_hf(raw)
    if (
        lower.startswith("ms:")
        or lower.startswith("modelscope:")
        or "modelscope.cn" in lower
        or "魔搭" in (name or "")
    ):
        return _dispatch_ms(raw)
    return []


def _dispatch_hf(url: str) -> list[ModelRecord]:
    lower = url.lower().strip()
    # hf:models[:sort|:pipeline:x|:search:q]
    rest = url.split(":", 1)[1] if ":" in url else "models"
    rest = rest.strip()
    if rest.lower().startswith("models"):
        rest = rest[6:].lstrip(":/")
    sort = "lastModified"
    search = ""
    pipeline = ""
    if not rest:
        pass
    elif rest.lower().startswith("pipeline:"):
        pipeline = rest.split(":", 1)[1].strip()
    elif rest.lower().startswith("search:"):
        search = rest.split(":", 1)[1].strip()
    elif rest.lower() in {"downloads", "likes", "trending", "lastmodified", "createdat"}:
        sort = "downloads" if rest.lower() == "trending" else rest
        if sort.lower() == "lastmodified":
            sort = "lastModified"
        if sort.lower() == "createdat":
            sort = "createdAt"
    elif re.fullmatch(r"[a-z0-9_.-]+", rest, flags=re.I) and "/" not in rest:
        # bare pipeline tag shorthand: hf:models:text-generation
        if rest.lower() not in {"models"}:
            pipeline = rest
    else:
        search = rest
    return fetch_huggingface_models(sort=sort, search=search, pipeline_tag=pipeline)


def _dispatch_ms(url: str) -> list[ModelRecord]:
    # ms:models | ms:models:downloads | ms:models:search:qwen
    if "://" in url:
        return fetch_modelscope_models()
    parts = url.split(":", 2)
    # modelscope:models:… or ms:models:…
    rest = ""
    if len(parts) >= 2:
        rest = ":".join(parts[1:]).strip()
    if rest.lower().startswith("models"):
        rest = rest[6:].lstrip(":/")
    sort = "GmtModified"
    search = ""
    if not rest:
        pass
    elif rest.lower().startswith("search:"):
        search = rest.split(":", 1)[1].strip()
    elif rest.lower() in {"downloads", "stars", "likes", "modified", "trending"}:
        sort = rest
    else:
        search = rest
    return fetch_modelscope_models(sort=sort, search=search)
