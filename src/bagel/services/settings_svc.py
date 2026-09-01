"""Settings service — filter tags + news sources."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.enums import KeywordRuleType, NetworkRequirement, Region, SourceType
from bagel.domain.models import IntelKeywordRule, IntelSource
from bagel.storage.repositories import KeywordRuleRepository, SourceRepository
from bagel.storage.seed import DEFAULT_SOURCES


class SettingsError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def list_filter_tags(session: Session) -> list[IntelKeywordRule]:
    return list(KeywordRuleRepository(session).list_by_type(KeywordRuleType.INCLUDE))


def list_exclude_tags(session: Session) -> list[IntelKeywordRule]:
    return list(KeywordRuleRepository(session).list_by_type(KeywordRuleType.EXCLUDE))


def add_filter_tag(session: Session, keyword: str, *, weight: float = 1.5) -> IntelKeywordRule:
    cleaned = (keyword or "").strip()
    if not cleaned:
        raise SettingsError("标签不能为空")
    repo = KeywordRuleRepository(session)
    existing = repo.find_by_keyword(cleaned, KeywordRuleType.INCLUDE)
    if existing:
        existing.enabled = True
        existing.weight = weight
        session.flush()
        return existing
    return repo.add(
        IntelKeywordRule(
            keyword=cleaned,
            rule_type=KeywordRuleType.INCLUDE,
            weight=weight,
            enabled=True,
        )
    )


def delete_filter_tag(session: Session, rule_id: UUID) -> None:
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None:
        raise SettingsError("标签不存在")
    repo.delete(rule)


def list_news_sources(session: Session) -> list[IntelSource]:
    return [
        s
        for s in SourceRepository(session).list_all()
        if s.source_type in {SourceType.RSS, SourceType.RSSHUB, SourceType.MANUAL}
    ]


def default_source_catalog() -> list[dict]:
    """Read-only catalog of built-in defaults for settings UI."""
    rows: list[dict] = []
    for row in DEFAULT_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.CN)),
                "source_type": str(row.get("source_type", SourceType.RSS)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_news_source(
    session: Session,
    *,
    name: str,
    url: str,
    region: str = "CN",
    source_type: str = "RSS",
) -> IntelSource:
    cleaned_name = (name or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_name or not cleaned_url:
        raise SettingsError("名称与 URL 不能为空")
    region_v = region.strip().upper() if region else "CN"
    if region_v not in {Region.CN, Region.GLOBAL}:
        raise SettingsError("region 仅支持 CN / GLOBAL")
    type_v = (source_type or "RSS").strip().upper()
    if type_v not in {SourceType.RSS, SourceType.RSSHUB, SourceType.MANUAL}:
        raise SettingsError("source_type 仅支持 RSS / RSSHUB / MANUAL")
    network = (
        NetworkRequirement.PROXY_PREFERRED
        if region_v == Region.GLOBAL
        else NetworkRequirement.DIRECT
    )
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=cleaned_url,
            source_type=type_v,
            region=region_v,
            network_requirement=network,
            priority=500,
            enabled=True,
        )
    )


def toggle_news_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    repo = SourceRepository(session)
    source = repo.get(source_id)
    if source is None:
        raise SettingsError("新闻源不存在")
    source.enabled = enabled
    session.flush()
    return source


def delete_news_source(session: Session, source_id: UUID) -> None:
    repo = SourceRepository(session)
    source = repo.get(source_id)
    if source is None:
        raise SettingsError("新闻源不存在")
    repo.delete(source)


def list_paper_sources(session: Session) -> list[IntelSource]:
    return [s for s in SourceRepository(session).list_all() if s.source_type == SourceType.PAPER]


def default_paper_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_PAPER_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_PAPER_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.PAPER)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_paper_source(
    session: Session,
    *,
    name: str,
    url: str,
) -> IntelSource:
    cleaned_name = (name or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_name or not cleaned_url:
        raise SettingsError("名称与 URL 不能为空")
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=cleaned_url,
            source_type=SourceType.PAPER,
            region=Region.GLOBAL,
            network_requirement=NetworkRequirement.PROXY_PREFERRED,
            priority=500,
            enabled=True,
        )
    )


def toggle_paper_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_paper_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)


def list_stock_sources(session: Session) -> list[IntelSource]:
    return [s for s in SourceRepository(session).list_all() if s.source_type == SourceType.STOCK]


def default_stock_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_STOCK_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_STOCK_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.STOCK)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_stock_source(
    session: Session,
    *,
    name: str,
    url: str,
    region: str = "GLOBAL",
) -> IntelSource:
    cleaned_name = (name or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_name or not cleaned_url:
        raise SettingsError("名称与 URL 不能为空")
    region_v = region.strip().upper() if region else "GLOBAL"
    if region_v not in {Region.CN, Region.GLOBAL}:
        raise SettingsError("region 仅支持 CN / GLOBAL")
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=cleaned_url,
            source_type=SourceType.STOCK,
            region=region_v,
            network_requirement=(
                NetworkRequirement.DIRECT if region_v == Region.CN else NetworkRequirement.PROXY_PREFERRED
            ),
            priority=500,
            enabled=True,
        )
    )


def toggle_stock_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_stock_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)
