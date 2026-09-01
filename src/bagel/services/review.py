"""Human review actions — favorite / ignore / top / deep-read."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus
from bagel.domain.models import IntelItem
from bagel.pipeline.category import classify_title
from bagel.storage.repositories import ItemRepository

DEFAULT_PAGE_SIZE = 20


@dataclass
class PageResult:
    items: list[IntelItem]
    total: int
    page: int
    page_size: int
    categories: list[str]

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)


class ReviewError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def get_item(session: Session, item_id: UUID) -> IntelItem:
    item = ItemRepository(session).get(item_id)
    if item is None:
        raise ReviewError("条目不存在")
    return item


def favorite(session: Session, item_id: UUID, *, value: bool = True) -> IntelItem:
    repo = ItemRepository(session)
    item = get_item(session, item_id)
    return repo.set_flags(item, is_favorite=value)


def ignore(session: Session, item_id: UUID) -> IntelItem:
    repo = ItemRepository(session)
    item = get_item(session, item_id)
    item.is_favorite = False
    return repo.set_status(item, ItemStatus.REJECTED)


def mark_top(session: Session, item_id: UUID, *, value: bool = True) -> IntelItem:
    repo = ItemRepository(session)
    item = get_item(session, item_id)
    return repo.set_flags(item, is_top=value)


def mark_deep_read(session: Session, item_id: UUID, *, value: bool = True) -> IntelItem:
    repo = ItemRepository(session)
    item = get_item(session, item_id)
    return repo.set_flags(item, is_deep_read=value)


def add_tags(session: Session, item_id: UUID, tags: list[str]) -> IntelItem:
    item = get_item(session, item_id)
    cleaned = [t.strip() for t in tags if t and t.strip()]
    existing = list(item.tags or [])
    item.tags = list(dict.fromkeys([*existing, *cleaned]))
    session.flush()
    return item


def _page_args(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    offset = (page - 1) * page_size
    return page, page_size, offset


def _ensure_categories(session: Session, items: list[IntelItem]) -> None:
    changed = False
    for item in items:
        if item.category:
            continue
        item.category = classify_title(item.title, item.summary)
        changed = True
    if changed:
        session.flush()


def list_candidates(
    session: Session,
    *,
    item_type: str | None = None,
    category: str | None = None,
    platform: str | None = None,
    owner_id=None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> PageResult:
    page, page_size, offset = _page_args(page, page_size)
    repo = ItemRepository(session)
    items = list(
        repo.list_by_status(
            ItemStatus.CANDIDATE,
            item_type=item_type,
            category=category or None,
            platform=platform or None,
            owner_id=owner_id,
            limit=page_size,
            offset=offset,
        )
    )
    _ensure_categories(session, items)
    total = repo.count_by_status(
        ItemStatus.CANDIDATE,
        item_type=item_type,
        category=category or None,
        platform=platform or None,
        owner_id=owner_id,
    )
    categories = list(
        repo.list_categories(
            ItemStatus.CANDIDATE,
            item_type=item_type,
            platform=platform or None,
            owner_id=owner_id,
        )
    )
    return PageResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        categories=categories,
    )


def list_favorites(
    session: Session,
    *,
    category: str | None = None,
    item_types: list[str] | None = None,
    platform: str | None = None,
    owner_id=None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> PageResult:
    page, page_size, offset = _page_args(page, page_size)
    repo = ItemRepository(session)
    items = list(
        repo.list_favorites(
            category=category or None,
            item_types=item_types,
            platform=platform or None,
            owner_id=owner_id,
            limit=page_size,
            offset=offset,
        )
    )
    _ensure_categories(session, items)
    total = repo.count_favorites(
        category=category or None,
        item_types=item_types,
        platform=platform or None,
        owner_id=owner_id,
    )
    fav_cats = {
        i.category
        for i in repo.list_favorites(
            item_types=item_types,
            platform=platform or None,
            owner_id=owner_id,
            limit=500,
            offset=0,
        )
        if i.category
    }
    return PageResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        categories=sorted(fav_cats),
    )


def list_ignored(
    session: Session,
    *,
    category: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> PageResult:
    page, page_size, offset = _page_args(page, page_size)
    repo = ItemRepository(session)
    items = list(
        repo.list_by_status(
            ItemStatus.REJECTED,
            category=category or None,
            limit=page_size,
            offset=offset,
        )
    )
    _ensure_categories(session, items)
    total = repo.count_by_status(ItemStatus.REJECTED, category=category or None)
    categories = list(repo.list_categories(ItemStatus.REJECTED))
    return PageResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        categories=categories,
    )


def list_selected(session: Session, *, limit: int = 100):
    return ItemRepository(session).list_by_status(
        [ItemStatus.SELECTED, ItemStatus.SUMMARIZED, ItemStatus.PUBLISHED],
        limit=limit,
    )
