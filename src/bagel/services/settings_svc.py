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
    from bagel.pipeline.education_tracks import TRACK_LABELS, build_education_url, normalize_track
    from bagel.storage.seed import DEFAULT_EDUCATION_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_EDUCATION_SOURCES:
        track = normalize_track(str(row.get("track") or "open_course"))
        facet = row.get("facet")
        rows.append(
            {
                "name": row["name"],
                "url": build_education_url(
                    str(row["url"]).strip(), track=track, facet=facet
                ),
                "fetch_url": str(row["url"]).strip(),
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.EDUCATION)),
                "enabled": bool(row.get("enabled", True)),
                "track": track.value,
                "track_label": TRACK_LABELS[track],
                "facet": facet or "",
            }
        )
    return rows


def add_education_source(
    session: Session,
    *,
    name: str,
    url: str,
    region: str = "GLOBAL",
    track: str = "open_course",
    facet: str | None = None,
) -> IntelSource:
    from bagel.pipeline.education_tracks import build_education_url, normalize_track, parse_education_url

    cleaned_name = (name or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_name or not cleaned_url:
        raise SettingsError("名称与 URL 不能为空")
    region_v = region.strip().upper() if region else "GLOBAL"
    if region_v not in {Region.CN, Region.GLOBAL}:
        raise SettingsError("region 仅支持 CN / GLOBAL")
    track_v = normalize_track(track)
    stored = build_education_url(cleaned_url, track=track_v, facet=facet)
    want_fetch = parse_education_url(stored).fetch_url
    # Idempotent: same fetch URL → enable / refresh prefix instead of duplicating.
    for existing in list_education_sources(session):
        existing_fetch = parse_education_url(existing.url or "").fetch_url
        if _norm_fetch(existing_fetch) == _norm_fetch(want_fetch):
            existing.enabled = True
            existing.url = stored
            existing.name = cleaned_name or existing.name
            existing.region = region_v
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=stored,
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


def _norm_fetch(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def add_education_presets(
    session: Session,
    *,
    query: str,
    kind: str,
    custom_url: str = "",
) -> dict:
    """Resolve city/school query → add matching presets; unmatched → watch: 订阅."""
    from bagel.collectors.education_watch import build_watch_url
    from bagel.pipeline.education_presets import list_presets, resolve_presets, suggest_labels
    from bagel.pipeline.education_tracks import EduTrack

    kind_v = (kind or "").strip().lower()
    if kind_v not in {"k12_region", "kaoyan_school", "kaoyan", "region", "school"}:
        raise SettingsError("kind 仅支持 k12_region / kaoyan_school")

    q = (query or "").strip()
    custom = (custom_url or "").strip()
    if not q and not custom:
        raise SettingsError("请输入省市/学校名称，或填写自定义 RSS / RSSHub 路径")

    is_k12 = kind_v in {"k12_region", "region"}
    track = EduTrack.K12 if is_k12 else EduTrack.KAOYAN
    default_facet = "city" if is_k12 else "prospectus"
    kind_label = "K12 省市" if is_k12 else "考研院校"

    matched: list = []
    unmatched: list[str] = []
    if q:
        # Raw feed pasted into the name field → treat as custom path.
        if _is_feed_ref(q) and not custom:
            custom = q
            q = ""
        else:
            matched, unmatched = resolve_presets(q, kind=kind_v)

    added_names: list[str] = []
    for preset in matched:
        add_education_source(
            session,
            name=preset.label,
            url=preset.fetch_url,
            region="CN",
            track=preset.track.value,
            facet=preset.facet,
        )
        added_names.append(preset.label)

    if custom:
        if not _is_feed_ref(custom):
            raise SettingsError(
                "自定义路径需为 RSS URL（https://…）、RSSHub 相对路径（以 / 开头）"
                f"或关注源（watch:…），当前为：{custom[:80]}"
            )
        display = (unmatched[0] if len(unmatched) == 1 else None) or (q if q and not matched else None)
        if not display:
            display = f"自定义·{kind_label}"
        else:
            display = f"{display}（自定义）"
        add_education_source(
            session,
            name=display[:120],
            url=custom,
            region="CN",
            track=track.value,
            facet=default_facet,
        )
        added_names.append(display)
        unmatched = []

    # Any remaining city/school → watch subscription (portal scrape + keyword).
    from bagel.collectors.education_portals import resolve_portal

    for token in list(unmatched):
        watch_kind = "k12" if is_k12 else "kaoyan"
        watch_url = build_watch_url(kind=watch_kind, query=token)
        portal = resolve_portal(token, kind=watch_kind)
        if portal:
            display = portal.label
        else:
            display = f"{token} · {'K12 关注' if is_k12 else '考研关注'}"
        add_education_source(
            session,
            name=display[:120],
            url=watch_url,
            region="CN",
            track=track.value,
            facet=portal.facet if portal else default_facet,
        )
        added_names.append(display)
    unmatched = []

    if not added_names:
        hints = "、".join(suggest_labels(kind_v)[:10])
        raise SettingsError(
            f"未能添加{kind_label}数据源。请输入省市/学校名称；"
            f"也可填写自定义 RSS / RSSHub / watch: 路径。已支持快捷：{hints}"
        )

    return {
        "added": len(added_names),
        "names": added_names,
        "unmatched": unmatched,
        "available": len(list_presets(kind_v)),
    }


def _is_feed_ref(raw: str) -> bool:
    text = (raw or "").strip()
    low = text.lower()
    return (
        low.startswith("http://")
        or low.startswith("https://")
        or text.startswith("/")
        or low.startswith("watch:")
    )

def education_preset_catalog() -> dict[str, list[dict]]:
    from bagel.pipeline.education_presets import preset_catalog_for_ui, suggest_labels

    catalog = preset_catalog_for_ui()
    catalog["k12_suggest"] = suggest_labels("k12_region")
    catalog["kaoyan_suggest"] = suggest_labels("kaoyan_school")
    return catalog


def toggle_education_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_education_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)


def list_av_sources(session: Session) -> list[IntelSource]:
    return [s for s in SourceRepository(session).list_all() if s.source_type == SourceType.AV]


def default_av_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_AV_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_AV_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.AV)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_av_source(
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
    if not cleaned_url.lower().startswith("av:") and not cleaned_url.startswith("http"):
        cleaned_url = f"av:generic:url:{cleaned_url}"
    region_v = region.strip().upper() if region else "GLOBAL"
    if region_v not in {Region.CN, Region.GLOBAL}:
        raise SettingsError("region 仅支持 CN / GLOBAL")
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=cleaned_url,
            source_type=SourceType.AV,
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


def toggle_av_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_av_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)


def list_wechat_mp_sources(session: Session) -> list[IntelSource]:
    return [
        s
        for s in SourceRepository(session).list_all()
        if s.source_type == SourceType.WECHAT and (s.url or "").startswith("wechat:mp:")
    ]


def add_wechat_mp_source(
    session: Session,
    *,
    name: str,
    wxid: str = "",
    biz: str = "",
    feed_url: str = "",
) -> IntelSource:
    from bagel.integrations.wechat_mp_discover import build_source_url

    cleaned_name = (name or "").strip()
    cleaned_wxid = (wxid or "").strip()
    cleaned_biz = (biz or "").strip()
    cleaned_feed = (feed_url or "").strip()
    if not cleaned_name and not cleaned_wxid and not cleaned_feed:
        raise SettingsError("请填写公众号名称，或 RSS 源地址（推荐 WeWe-RSS）")
    try:
        url = build_source_url(
            name=cleaned_name or cleaned_wxid,
            wxid=cleaned_wxid,
            biz=cleaned_biz,
            feed_url=cleaned_feed,
        )
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    display = cleaned_name or cleaned_wxid or cleaned_feed
    repo = SourceRepository(session)
    for existing in list_wechat_mp_sources(session):
        if existing.name == display or existing.url == url:
            existing.enabled = True
            # Merge richer identity into existing row
            from bagel.integrations.wechat_mp_discover import parse_source_url

            cur = parse_source_url(existing.url or "")
            existing.url = build_source_url(
                name=cleaned_name or cur.name or existing.name,
                wxid=cleaned_wxid or cur.wxid,
                biz=cleaned_biz or cur.biz,
                feed_url=cleaned_feed or cur.feed_url,
            )
            if cleaned_name:
                existing.name = cleaned_name
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
    return repo.add(
        IntelSource(
            name=display[:200],
            url=url,
            source_type=SourceType.WECHAT,
            region=Region.CN,
            network_requirement=NetworkRequirement.DIRECT,
            priority=400,
            enabled=True,
        )
    )


def toggle_wechat_mp_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_wechat_mp_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)
