"""Bridge MediaCrawler video posts into the yt-dlp AV learning queue."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import IntelItem
from bagel.integrations.ytdlp import _platform_from_url
from bagel.pipeline.category import classify_title
from bagel.storage.repositories import canonicalize_url, content_hash

ProgressCallback = Callable[..., None]

VIDEO_MEDIA_PLATFORMS = frozenset({"bili", "dy", "ks", "bilibili", "douyin", "kuaishou"})

_VIDEO_URL_HINTS = (
    "bilibili.com/video/",
    "b23.tv/",
    "douyin.com/video/",
    "iesdouyin.com/",
    "kuaishou.com/short-video/",
    "kuaishou.com/fshort-video/",
    "chenzhongtech.com/",
)

_RICH_MIN_CHARS = 120


@dataclass
class AvImportResult:
    av_item: IntelItem
    media_item: IntelItem
    created: bool

    @property
    def detail_url(self) -> str:
        return f"/av/items/{self.av_item.id}"


@dataclass
class EnrichTranscriptResult:
    media_item: IntelItem | None
    av_item: IntelItem
    created_av: bool
    subtitle_status: str
    chars: int
    error: str | None = None


def media_post_platform(item: IntelItem) -> str:
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    plat = str(meta.get("platform") or "").strip().lower()
    if plat:
        return plat
    for tag in item.tags or []:
        t = str(tag).strip().lower()
        if t in VIDEO_MEDIA_PLATFORMS:
            return t
    return ""


def linked_av_id(item: IntelItem) -> str | None:
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    raw = meta.get("av_item_id")
    if raw:
        return str(raw)
    return None


def _url_looks_like_video(url: str, plat: str) -> bool:
    lower = (url or "").lower()
    if not lower.startswith(("http://", "https://")):
        return False
    if plat in {"bili", "bilibili"}:
        return "bilibili.com/video/" in lower or "b23.tv/" in lower
    if plat in {"dy", "douyin"}:
        return "douyin.com" in lower or "iesdouyin.com" in lower
    if plat in {"ks", "kuaishou"}:
        return "kuaishou.com" in lower or "chenzhongtech.com" in lower
    return any(h in lower for h in _VIDEO_URL_HINTS)


def is_importable_media_post(item: IntelItem) -> bool:
    if getattr(item, "item_type", None) != ItemType.MEDIA_POST:
        return False
    if linked_av_id(item):
        return False
    return _url_looks_like_video((item.url or "").strip(), media_post_platform(item))


def item_has_rich_transcript(item: IntelItem) -> bool:
    content = (item.content or "").strip()
    if len(content) >= _RICH_MIN_CHARS:
        return True
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    sub = meta.get("subtitle") if isinstance(meta.get("subtitle"), dict) else {}
    if sub.get("status") == "done" and (sub.get("text_preview") or sub.get("text")):
        return True
    return False


def can_enrich_media_transcript(item: IntelItem) -> bool:
    """Video media post that can be (re)filled via yt-dlp subtitles."""
    if getattr(item, "item_type", None) != ItemType.MEDIA_POST:
        return False
    if item_has_rich_transcript(item):
        return False
    if linked_av_id(item):
        return True
    return _url_looks_like_video((item.url or "").strip(), media_post_platform(item))


def _find_av_for_url(session: Session, url: str) -> IntelItem | None:
    canonical = canonicalize_url(url)
    prefixed = f"av:{canonical}"
    return session.scalar(
        select(IntelItem).where(
            IntelItem.item_type == ItemType.AV,
            or_(
                IntelItem.url == url,
                IntelItem.canonical_url == canonical,
                IntelItem.canonical_url == prefixed,
            ),
        )
    )


def import_media_post_to_av(
    session: Session,
    media_item_id: uuid.UUID | str,
    *,
    owner_id: uuid.UUID | None = None,
) -> AvImportResult:
    try:
        mid = media_item_id if isinstance(media_item_id, uuid.UUID) else uuid.UUID(str(media_item_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("无效条目 ID") from exc

    media = session.get(IntelItem, mid)
    if not media or media.item_type != ItemType.MEDIA_POST:
        raise ValueError("条目不存在或不是自媒体类型")

    existing_link = linked_av_id(media)
    if existing_link:
        av = session.get(IntelItem, uuid.UUID(existing_link))
        if av and av.item_type == ItemType.AV:
            return AvImportResult(av_item=av, media_item=media, created=False)

    if not is_importable_media_post(media):
        raise ValueError("该条目不是可学习的视频链接（仅支持 B 站/抖音/快手视频页）")

    url = (media.url or "").strip()
    existing_av = _find_av_for_url(session, url)
    if existing_av:
        media_meta: dict[str, Any] = dict(media.metadata_ if isinstance(media.metadata_, dict) else {})
        media_meta["av_item_id"] = str(existing_av.id)
        media.metadata_ = media_meta
        session.flush()
        return AvImportResult(av_item=existing_av, media_item=media, created=False)

    platform = _platform_from_url(url)
    meta = media.metadata_ if isinstance(media.metadata_, dict) else {}
    summary = (media.summary or "")[:800]
    status = media.status if media.status != ItemStatus.REJECTED else ItemStatus.CANDIDATE
    tags = list({platform, "from_media", *(media.tags or [])})[:12]
    canonical = canonicalize_url(url)
    av_canonical = f"av:{canonical}"
    digest = content_hash(av_canonical, media.title or "")

    av_item = IntelItem(
        item_type=ItemType.AV,
        source_type=SourceType.AV,
        source_id=None,
        owner_id=owner_id or media.owner_id,
        title=(media.title or "")[:500],
        summary=summary,
        url=url,
        canonical_url=av_canonical,
        author=media.author,
        published_at=media.published_at,
        content_hash=digest,
        status=status,
        score=float(media.score or 1.0),
        tags=tags,
        category=media.category or classify_title(media.title or "", summary),
        metadata_={
            "platform": platform,
            "external_id": meta.get("external_id"),
            "media_kind": "video",
            "source_name": "自媒体导入",
            "from_media_id": str(media.id),
            "download": {"status": "none"},
            "subtitle": {"status": "none"},
        },
    )
    session.add(av_item)
    session.flush()
    created = True

    media_meta = dict(meta)
    media_meta["av_item_id"] = str(av_item.id)
    media.metadata_ = media_meta
    session.flush()

    return AvImportResult(av_item=av_item, media_item=media, created=created)


def _sync_transcript_to_media(media: IntelItem, av: IntelItem, text: str) -> None:
    body = (text or "").strip()
    if not body:
        return
    media.content = body[:50000]
    media_meta: dict[str, Any] = dict(media.metadata_ if isinstance(media.metadata_, dict) else {})
    av_meta = av.metadata_ if isinstance(av.metadata_, dict) else {}
    sub = av_meta.get("subtitle") if isinstance(av_meta.get("subtitle"), dict) else {}
    media_meta["av_item_id"] = str(av.id)
    media_meta["rich_source"] = "ytdlp_subtitle"
    media_meta["subtitle"] = {
        "status": sub.get("status") or "done",
        "text_preview": body[:500],
        "chars": len(body),
    }
    media.metadata_ = media_meta


def enrich_media_transcript(
    session: Session,
    media_item_id: uuid.UUID | str,
    *,
    owner_id: uuid.UUID | None = None,
    on_progress: ProgressCallback | None = None,
) -> EnrichTranscriptResult:
    """Import media video into AV queue and extract subtitles via yt-dlp."""
    from bagel.jobs.av import run_extract_av_subtitles

    imported = import_media_post_to_av(session, media_item_id, owner_id=owner_id)
    av = imported.av_item
    media = imported.media_item

    if item_has_rich_transcript(av) and (av.content or "").strip():
        _sync_transcript_to_media(media, av, av.content or "")
        session.flush()
        return EnrichTranscriptResult(
            media_item=media,
            av_item=av,
            created_av=imported.created,
            subtitle_status="done",
            chars=len((av.content or "").strip()),
        )

    if on_progress:
        on_progress(current=4, total=10, message="提取文稿（字幕/ASR）…", percent=40.0)
    from bagel.services import user_config as user_cfg

    result = run_extract_av_subtitles(
        session,
        item_id=av.id,
        on_progress=on_progress,
        settings=user_cfg.settings_for_user(owner_id),
    )
    session.refresh(av)
    text = (av.content or "").strip()
    if result.get("status") == "SUCCESS" and text:
        _sync_transcript_to_media(media, av, text)
        session.flush()
        return EnrichTranscriptResult(
            media_item=media,
            av_item=av,
            created_av=imported.created,
            subtitle_status="done",
            chars=len(text),
        )
    err = str(result.get("error") or "字幕提取失败")
    return EnrichTranscriptResult(
        media_item=media,
        av_item=av,
        created_av=imported.created,
        subtitle_status="failed",
        chars=0,
        error=err,
    )


def enrich_items_for_brief(
    session: Session,
    items: list[IntelItem],
    *,
    max_items: int = 8,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Fill transcript text for MEDIA/AV rows before summarization."""
    from bagel.jobs.av import run_extract_av_subtitles

    budget = max(0, int(max_items or 0))
    enriched = 0
    skipped = 0
    failed: list[str] = []

    for i, item in enumerate(items):
        if enriched >= budget:
            break
        if item_has_rich_transcript(item):
            skipped += 1
            continue
        if on_progress:
            on_progress(
                current=i + 1,
                total=max(len(items), 1),
                message=f"充实文稿 {i + 1}/{len(items)}：{(item.title or '')[:32]}",
                percent=min(90.0, 10.0 + 80.0 * (i + 1) / max(len(items), 1)),
            )
        try:
            if item.item_type == ItemType.MEDIA_POST and can_enrich_media_transcript(item):
                out = enrich_media_transcript(session, item.id)
                if out.subtitle_status == "done":
                    enriched += 1
                else:
                    failed.append(out.error or item.title or str(item.id))
            elif item.item_type == ItemType.AV:
                result = run_extract_av_subtitles(session, item_id=item.id)
                if result.get("status") == "SUCCESS":
                    enriched += 1
                else:
                    failed.append(str(result.get("error") or item.title or str(item.id)))
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{(item.title or '')[:40]}: {exc}"[:160])

    return {
        "enriched": enriched,
        "skipped": skipped,
        "failed": failed[:12],
        "attempted_budget": budget,
    }
