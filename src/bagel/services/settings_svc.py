"""Settings service — interest tags, exclude rules, typed data sources."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.enums import KeywordRuleType, NetworkRequirement, Region, SourceType
from bagel.domain.models import IntelGithubQuery, IntelKeywordRule, IntelSource
from bagel.pipeline.keyword_scopes import (
    ALL_SCOPES,
    INCLUDE_SCOPES,
    SCOPE_TO_TAB,
    effective_scopes,
    rule_applies_to,
    serialize_scopes,
)
from bagel.storage.repositories import (
    GithubQueryRepository,
    KeywordRuleRepository,
    SourceRepository,
)
from bagel.storage.seed import DEFAULT_SOURCES


class SettingsError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def list_filter_tags(session: Session, *, scope: str | None = None) -> list[IntelKeywordRule]:
    """INCLUDE interest tags, optionally filtered to one resource scope."""
    rows = list(KeywordRuleRepository(session).list_by_type(KeywordRuleType.INCLUDE))
    if scope is None:
        return rows
    return [r for r in rows if rule_applies_to(r, scope)]


def list_exclude_tags(session: Session) -> list[IntelKeywordRule]:
    return list(KeywordRuleRepository(session).list_by_type(KeywordRuleType.EXCLUDE))


def add_filter_tag(
    session: Session,
    keyword: str,
    *,
    scope: str,
    weight: float = 1.5,
) -> IntelKeywordRule:
    cleaned = (keyword or "").strip()
    if not cleaned:
        raise SettingsError("标签不能为空")
    scope_key = (scope or "").strip().lower()
    if scope_key not in INCLUDE_SCOPES:
        raise SettingsError("兴趣标签类目无效")
    repo = KeywordRuleRepository(session)
    existing = repo.find_by_keyword(cleaned, KeywordRuleType.INCLUDE)
    if existing:
        scopes = effective_scopes(existing)
        if scope_key not in scopes:
            scopes.append(scope_key)
        existing.scopes = serialize_scopes(scopes)
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
            scopes=scope_key,
        )
    )


def delete_filter_tag(
    session: Session,
    rule_id: UUID,
    *,
    scope: str | None = None,
) -> None:
    """Delete INCLUDE rule, or detach one scope when still used elsewhere."""
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None or rule.rule_type != KeywordRuleType.INCLUDE:
        raise SettingsError("标签不存在")
    if scope:
        scopes = [s for s in effective_scopes(rule) if s != scope]
        if scopes:
            rule.scopes = serialize_scopes(scopes)
            session.flush()
            return
    repo.delete(rule)


def toggle_filter_tag(session: Session, rule_id: UUID, *, enabled: bool) -> IntelKeywordRule:
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None or rule.rule_type != KeywordRuleType.INCLUDE:
        raise SettingsError("标签不存在")
    rule.enabled = bool(enabled)
    session.flush()
    return rule


def add_exclude_tag(
    session: Session,
    keyword: str,
    *,
    scopes: list[str] | None = None,
) -> IntelKeywordRule:
    cleaned = (keyword or "").strip()
    if not cleaned:
        raise SettingsError("排除词不能为空")
    wanted = serialize_scopes(scopes or list(ALL_SCOPES))
    if not wanted:
        raise SettingsError("请至少选择一个适用类目")
    repo = KeywordRuleRepository(session)
    existing = repo.find_by_keyword(cleaned, KeywordRuleType.EXCLUDE)
    if existing:
        existing.scopes = wanted
        existing.enabled = True
        session.flush()
        return existing
    return repo.add(
        IntelKeywordRule(
            keyword=cleaned,
            rule_type=KeywordRuleType.EXCLUDE,
            weight=0.0,
            enabled=True,
            scopes=wanted,
        )
    )


def update_exclude_tag(
    session: Session,
    rule_id: UUID,
    *,
    scopes: list[str],
) -> IntelKeywordRule:
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None or rule.rule_type != KeywordRuleType.EXCLUDE:
        raise SettingsError("排除词不存在")
    wanted = serialize_scopes(scopes)
    if not wanted:
        raise SettingsError("请至少选择一个适用类目")
    rule.scopes = wanted
    session.flush()
    return rule


def delete_exclude_tag(session: Session, rule_id: UUID) -> None:
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None or rule.rule_type != KeywordRuleType.EXCLUDE:
        raise SettingsError("排除词不存在")
    repo.delete(rule)


def toggle_exclude_tag(session: Session, rule_id: UUID, *, enabled: bool) -> IntelKeywordRule:
    repo = KeywordRuleRepository(session)
    rule = repo.get(rule_id)
    if rule is None or rule.rule_type != KeywordRuleType.EXCLUDE:
        raise SettingsError("排除词不存在")
    rule.enabled = bool(enabled)
    session.flush()
    return rule


def scope_labels_for_rule(rule: IntelKeywordRule) -> list[str]:
    from bagel.pipeline.keyword_scopes import SCOPE_LABELS

    return [SCOPE_LABELS.get(s, s) for s in effective_scopes(rule)]


def redirect_tab_for_scope(scope: str) -> str:
    return SCOPE_TO_TAB.get(scope, "sources")


def list_github_queries(session: Session) -> list[IntelGithubQuery]:
    return list(GithubQueryRepository(session).list_all())


def toggle_github_query(session: Session, query_id: UUID, *, enabled: bool) -> IntelGithubQuery:
    repo = GithubQueryRepository(session)
    row = repo.get(query_id)
    if row is None:
        raise SettingsError("GitHub Query 不存在")
    row.enabled = bool(enabled)
    session.flush()
    return row


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


def list_model_sources(session: Session) -> list[IntelSource]:
    return [s for s in SourceRepository(session).list_all() if s.source_type == SourceType.MODEL]


def default_model_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_MODEL_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_MODEL_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.MODEL)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_model_source(
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
            source_type=SourceType.MODEL,
            region=region_v,
            network_requirement=(
                NetworkRequirement.DIRECT
                if region_v == Region.CN
                else NetworkRequirement.PROXY_PREFERRED
            ),
            priority=500,
            enabled=True,
        )
    )


def toggle_model_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_model_source(session: Session, source_id: UUID) -> None:
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
                NetworkRequirement.DIRECT
                if region_v == Region.CN
                else NetworkRequirement.PROXY_PREFERRED
            ),
            priority=500,
            enabled=True,
        )
    )


def toggle_stock_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_stock_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)


def list_education_sources(session: Session) -> list[IntelSource]:
    return [
        s for s in SourceRepository(session).list_all() if s.source_type == SourceType.EDUCATION
    ]


def default_education_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_EDUCATION_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_EDUCATION_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.EDUCATION)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_education_source(
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
            source_type=SourceType.EDUCATION,
            region=region_v,
            network_requirement=(
                NetworkRequirement.DIRECT
                if region_v == Region.CN
                else NetworkRequirement.PROXY_PREFERRED
            ),
            priority=500,
            enabled=True,
        )
    )


def toggle_education_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_education_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)
