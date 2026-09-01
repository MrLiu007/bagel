"""Monthly / weekly brief service — generate, persist, export markdown.

Period membership is defined strictly by item.published_at (source publish time),
never by fetched_at / first_seen_at (ingest time).

Period keys:
  - month: YYYY-MM
  - week:  YYYY-Www (ISO week, Monday–Sunday)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Sequence

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus
from bagel.domain.models import IntelItem, IntelMonthlyBrief
from bagel.services.monthly_templates import (
    TEMPLATE_VERSION,
    item_types_for_kind,
    render_monthly_brief,
)
from bagel.settings import Settings, get_settings

PeriodType = Literal["month", "week"]

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@dataclass
class MonthlyBriefBundle:
    year_month: str
    kind: str
    title: str
    markdown: str
    item_count: int
    path_md: Path
    brief: IntelMonthlyBrief
    period_type: PeriodType = "month"


def period_type_of(period_key: str) -> PeriodType:
    if _WEEK_RE.match((period_key or "").strip()):
        return "week"
    return "month"


def scope_label(period_type: PeriodType) -> str:
    return "本周" if period_type == "week" else "本月"


def parse_year_month(value: str | None = None, *, now: datetime | None = None) -> str:
    if value:
        text = value.strip()
        datetime.strptime(text, "%Y-%m")  # validate
        return text
    now = now or datetime.now(UTC)
    return now.strftime("%Y-%m")


def parse_year_week(value: str | None = None, *, now: datetime | None = None) -> str:
    if value:
        text = value.strip().upper()
        m = _WEEK_RE.match(text)
        if not m:
            raise ValueError(f"invalid ISO week: {value!r} (expected YYYY-Www)")
        year, week = int(m.group(1)), int(m.group(2))
        # Validate via fromisocalendar
        datetime.fromisocalendar(year, week, 1)
        return f"{year}-W{week:02d}"
    now = now or datetime.now(UTC)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def parse_period(
    value: str | None = None,
    *,
    period: PeriodType = "month",
    now: datetime | None = None,
) -> str:
    if period == "week":
        return parse_year_week(value, now=now)
    if value and _WEEK_RE.match(value.strip().upper()):
        # Allow week keys even when period defaulted to month (e.g. export URL).
        return parse_year_week(value, now=now)
    return parse_year_month(value, now=now)


def week_date_range(period_key: str) -> tuple[datetime, datetime]:
    """Inclusive Monday 00:00 UTC → exclusive next Monday."""
    key = parse_year_week(period_key)
    m = _WEEK_RE.match(key)
    assert m
    year, week = int(m.group(1)), int(m.group(2))
    start = datetime.fromisocalendar(year, week, 1).replace(tzinfo=UTC)
    end = start + timedelta(days=7)
    return start, end


def format_period_option(period_key: str) -> str:
    """Human label for <select> options."""
    if period_type_of(period_key) == "week":
        start, end = week_date_range(period_key)
        last = end - timedelta(seconds=1)
        return f"{period_key}（{start.month}/{start.day}–{last.month}/{last.day}）"
    return period_key


def list_available_months_portable(session: Session, *, kind: str) -> list[str]:
    """Months that have at least one item with published_at in that month."""
    return list_available_periods(session, kind=kind, period="month")


def list_available_periods(
    session: Session,
    *,
    kind: str,
    period: PeriodType = "month",
) -> list[str]:
    types = item_types_for_kind(kind)
    items = session.scalars(
        select(IntelItem).where(
            IntelItem.item_type.in_(types),
            IntelItem.status != ItemStatus.REJECTED,
            IntelItem.published_at.is_not(None),
        )
    ).all()
    keys: set[str] = set()
    for item in items:
        if not item.published_at:
            continue
        dt = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=UTC)
        if period == "week":
            y, w, _ = dt.isocalendar()
            keys.add(f"{y}-W{w:02d}")
        else:
            keys.add(dt.strftime("%Y-%m"))

    brief_keys = session.scalars(
        select(IntelMonthlyBrief.year_month).where(IntelMonthlyBrief.kind == kind)
    ).all()
    for bk in brief_keys:
        if period == "week" and period_type_of(bk) == "week":
            keys.add(bk)
        elif period == "month" and period_type_of(bk) == "month":
            keys.add(bk)
    return sorted(keys, reverse=True)


def collect_month_items(
    session: Session,
    *,
    kind: str,
    year_month: str,
    limit: int = 300,
) -> list[IntelItem]:
    """Collect items whose published_at falls in year_month (publish time only)."""
    return collect_period_items(session, kind=kind, period_key=year_month, limit=limit)


def collect_period_items(
    session: Session,
    *,
    kind: str,
    period_key: str,
    limit: int = 300,
) -> list[IntelItem]:
    types = item_types_for_kind(kind)
    key = period_key.strip()
    if period_type_of(key) == "week":
        start, end = week_date_range(key)
        items = list(
            session.scalars(
                select(IntelItem)
                .where(
                    IntelItem.item_type.in_(types),
                    IntelItem.status != ItemStatus.REJECTED,
                    IntelItem.published_at.is_not(None),
                    IntelItem.published_at >= start,
                    IntelItem.published_at < end,
                )
                .order_by(IntelItem.published_at.desc(), IntelItem.score.desc())
                .limit(limit)
            ).all()
        )
    else:
        ym = parse_year_month(key)
        year, month = map(int, ym.split("-"))
        items = list(
            session.scalars(
                select(IntelItem)
                .where(
                    IntelItem.item_type.in_(types),
                    IntelItem.status != ItemStatus.REJECTED,
                    IntelItem.published_at.is_not(None),
                    extract("year", IntelItem.published_at) == year,
                    extract("month", IntelItem.published_at) == month,
                )
                .order_by(IntelItem.published_at.desc(), IntelItem.score.desc())
                .limit(limit)
            ).all()
        )
    items.sort(
        key=lambda i: (
            1 if i.is_top else 0,
            float(i.score or 0),
            i.published_at.timestamp() if i.published_at else 0.0,
        ),
        reverse=True,
    )
    return items


def get_brief(session: Session, *, kind: str, year_month: str) -> IntelMonthlyBrief | None:
    return session.scalar(
        select(IntelMonthlyBrief).where(
            IntelMonthlyBrief.kind == kind,
            IntelMonthlyBrief.year_month == year_month,
        )
    )


def list_briefs(session: Session, *, kind: str, limit: int = 24) -> Sequence[IntelMonthlyBrief]:
    return session.scalars(
        select(IntelMonthlyBrief)
        .where(IntelMonthlyBrief.kind == kind)
        .order_by(IntelMonthlyBrief.year_month.desc())
        .limit(limit)
    ).all()


def write_monthly_brief(
    session: Session,
    *,
    kind: str,
    year_month: str | None = None,
    period: PeriodType | None = None,
    settings: Settings | None = None,
) -> MonthlyBriefBundle:
    settings = settings or get_settings()
    if kind not in {
        BriefKind.NEWS,
        BriefKind.GITHUB,
        BriefKind.SCIENCE,
        BriefKind.MEDIA,
        BriefKind.STOCK,
    }:
        raise ValueError(f"unsupported brief kind: {kind}")

    if period is None:
        period = period_type_of(year_month) if year_month else "month"
    ym = parse_period(year_month, period=period)
    ptype = period_type_of(ym)

    items = collect_period_items(session, kind=kind, period_key=ym)
    now = datetime.now(UTC)
    md = render_monthly_brief(
        kind=kind,
        year_month=ym,
        items=items,
        generated_at=now,
        period_type=ptype,
    )
    kind_labels = {
        BriefKind.NEWS: "新闻总结",
        BriefKind.GITHUB: "项目总结",
        BriefKind.SCIENCE: "论文总结",
        BriefKind.MEDIA: "自媒体总结",
        BriefKind.STOCK: "股票总结",
    }
    kind_label = kind_labels[kind]
    cadence = "周总结" if ptype == "week" else "月总结"
    title = f"{ym} {kind_label}（{cadence}）"

    brief = get_brief(session, kind=kind, year_month=ym)
    meta = {
        "item_ids": [str(i.id) for i in items[:80]],
        "categories": sorted({(i.category or "其他") for i in items}),
        "top_titles": [(i.llm_title_zh or i.title) for i in items[:8]],
        "time_basis": "published_at",
        "period_type": ptype,
    }
    if brief is None:
        brief = IntelMonthlyBrief(
            year_month=ym,
            kind=kind,
            title=title,
            markdown=md,
            item_count=len(items),
            template_version=TEMPLATE_VERSION,
            status="READY",
            metadata_=meta,
            generated_at=now,
        )
        session.add(brief)
    else:
        brief.title = title
        brief.markdown = md
        brief.item_count = len(items)
        brief.template_version = TEMPLATE_VERSION
        brief.status = "READY"
        brief.metadata_ = meta
        brief.generated_at = now
    session.flush()

    out_dir = Path(settings.data_dir) / "briefs" / kind.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    path_md = out_dir / f"{ym}.md"
    path_md.write_text(md, encoding="utf-8")

    from bagel.services import wiki as wiki_svc

    wiki_svc.export_monthly_brief(brief, settings)

    return MonthlyBriefBundle(
        year_month=ym,
        kind=kind,
        title=title,
        markdown=md,
        item_count=len(items),
        path_md=path_md,
        brief=brief,
        period_type=ptype,
    )
