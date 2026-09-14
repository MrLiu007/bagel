"""City / school subscriptions: portal scrape first, keyword watch as supplement."""

from __future__ import annotations

from bagel.collectors.education import EducationRecord
from bagel.collectors.education_chsi import fetch_chsi_watch
from bagel.collectors.education_html_list import scrape_list_page
from bagel.collectors.education_moe import MOE_LIST_PAGES, fetch_moe_list
from bagel.collectors.education_portals import resolve_portal


def parse_watch_ref(fetch_url: str) -> tuple[str, str] | None:
    """Parse ``watch:k12:成都`` / ``watch:kaoyan:四川大学``."""
    raw = (fetch_url or "").strip()
    if not raw.lower().startswith("watch:"):
        return None
    body = raw[6:]
    kind, _, needle = body.partition(":")
    kind = kind.strip().lower()
    needle = needle.strip()
    if kind not in {"k12", "kaoyan"} or not needle:
        return None
    return kind, needle


def build_watch_url(*, kind: str, query: str) -> str:
    k = "k12" if kind in {"k12", "k12_region", "region"} else "kaoyan"
    return f"watch:{k}:{(query or '').strip()}"


def fetch_watch(name: str, fetch_url: str, *, max_results: int = 30) -> list[EducationRecord]:
    parsed = parse_watch_ref(fetch_url)
    if not parsed:
        raise ValueError(f"无效关注源：{fetch_url}")
    kind, needle = parsed
    display = name or (f"{needle} · K12 关注" if kind == "k12" else f"{needle} · 考研关注")

    collected: list[EducationRecord] = []
    seen: set[str] = set()

    def _extend(rows: list[EducationRecord]) -> None:
        for row in rows:
            if row.url in seen:
                continue
            seen.add(row.url)
            collected.append(row)

    portal = resolve_portal(needle, kind=kind)
    if portal:
        for list_url in portal.list_urls:
            try:
                rows = scrape_list_page(
                    display,
                    list_url,
                    institution=portal.institution,
                    tags=[needle, portal.institution, "门户直连"],
                    max_results=max_results,
                )
            except Exception:
                continue
            _extend(rows)
            if len(collected) >= max_results:
                return collected[:max_results]

    # Supplement: national lists filtered by alias (helps when portal is sparse).
    try:
        if kind == "kaoyan":
            _extend(fetch_chsi_watch(display, needle, max_results=max_results))
        else:
            _extend(fetch_k12_keyword(display, needle, max_results=max_results))
    except Exception:
        pass

    if collected:
        return collected[:max_results]

    # Last resort: keep source healthy — surface national policy as soft context
    # rather than failing the whole education collect job.
    soft = _soft_national(display, kind=kind, needle=needle, max_results=min(12, max_results))
    if soft:
        return soft

    # Truly empty: return [] (success, 0 items) instead of raising — avoids
    # permanent "failed" for valid subscriptions during off-season.
    return []


def fetch_k12_keyword(name: str, city: str, *, max_results: int = 30) -> list[EducationRecord]:
    aliases = _city_aliases(city)
    collected: list[EducationRecord] = []
    seen: set[str] = set()
    for moe_type in ("newest_file", "notice", "policy_anal", "edu_focus_news", "edu_ministry_news"):
        if moe_type not in MOE_LIST_PAGES:
            continue
        try:
            rows = fetch_moe_list(name, moe_type, max_results=40)
        except Exception:
            continue
        for row in rows:
            if not any(a in row.title for a in aliases):
                continue
            if row.url in seen:
                continue
            seen.add(row.url)
            row.tags = list({*(row.tags or []), city, "关注地区"})[:8]
            collected.append(row)
            if len(collected) >= max_results:
                return collected
    return collected


def _soft_national(
    name: str,
    *,
    kind: str,
    needle: str,
    max_results: int,
) -> list[EducationRecord]:
    """When portal + keyword miss, still return recent national items tagged as兜底."""
    rows: list[EducationRecord] = []
    try:
        if kind == "kaoyan":
            from bagel.collectors.education_chsi import fetch_chsi_list

            for key in ("kydt", "zcdh"):
                try:
                    rows.extend(fetch_chsi_list(name, key, max_results=max_results))
                except Exception:
                    continue
                if len(rows) >= max_results:
                    break
        else:
            for moe_type in ("edu_ministry_news", "newest_file", "notice"):
                try:
                    rows.extend(fetch_moe_list(name, moe_type, max_results=max_results))
                except Exception:
                    continue
                if len(rows) >= max_results:
                    break
    except Exception:
        return []

    out: list[EducationRecord] = []
    seen: set[str] = set()
    for row in rows:
        if row.url in seen:
            continue
        seen.add(row.url)
        row.tags = list({*(row.tags or []), needle, "全国兜底"})[:8]
        row.summary = (row.summary or "") + f"（暂无「{needle}」专属条目，附全国相关资讯）"
        out.append(row)
        if len(out) >= max_results:
            break
    return out


def _city_aliases(city: str) -> list[str]:
    raw = (city or "").strip()
    aliases = [raw]
    mapping = {
        "北京": ["北京", "北京市"],
        "上海": ["上海", "上海市"],
        "天津": ["天津", "天津市"],
        "重庆": ["重庆", "重庆市"],
        "广东": ["广东", "广东省", "广州", "深圳"],
        "广州": ["广州", "广州市", "广东"],
        "深圳": ["深圳", "深圳市"],
        "江苏": ["江苏", "江苏省", "南京", "苏州"],
        "浙江": ["浙江", "浙江省", "杭州"],
        "杭州": ["杭州", "杭州市", "浙江"],
        "四川": ["四川", "四川省", "成都"],
        "成都": ["成都", "成都市", "四川"],
        "湖北": ["湖北", "湖北省", "武汉"],
        "武汉": ["武汉", "武汉市", "湖北"],
        "湖南": ["湖南", "湖南省", "长沙"],
        "山东": ["山东", "山东省", "济南", "青岛"],
        "河南": ["河南", "河南省", "郑州"],
        "陕西": ["陕西", "陕西省", "西安"],
        "西安": ["西安", "西安市", "陕西"],
        "福建": ["福建", "福建省", "福州", "厦门"],
        "安徽": ["安徽", "安徽省", "合肥"],
        "辽宁": ["辽宁", "辽宁省", "沈阳", "大连"],
        "河北": ["河北", "河北省", "石家庄"],
    }
    for key, vals in mapping.items():
        if raw in vals or raw == key:
            return list(dict.fromkeys(vals))
    if raw.endswith(("市", "省", "区", "县")) and len(raw) > 1:
        aliases.append(raw[:-1])
    return list(dict.fromkeys(aliases))
