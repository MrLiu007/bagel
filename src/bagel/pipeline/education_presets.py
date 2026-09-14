"""Curated K12 region / 考研 school presets → fetch paths or watch: subscriptions.

Users type a city or university alias; we resolve to known-good routes and hand
them to ``add_education_source``. Unmatched queries become ``watch:`` keyword
subscriptions (教育部 / 研招网标题过滤) instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass

from bagel.pipeline.education_tracks import EduTrack


@dataclass(frozen=True)
class EducationPreset:
    key: str
    label: str
    aliases: tuple[str, ...]
    track: EduTrack
    facet: str
    fetch_url: str
    kind: str  # region | school | national
    note: str = ""


# --- K12: provinces / cities with RSSHub gov education routes ---
K12_REGION_PRESETS: tuple[EducationPreset, ...] = (
    EducationPreset(
        key="beijing-bjeea",
        label="北京教育考试院 · 公告",
        aliases=("北京", "北京市", "beijing", "京", "北京教委", "北京考试院"),
        track=EduTrack.K12,
        facet="city",
        fetch_url="/gov/beijing/bjeea/bjeeagg",
        kind="region",
        note="招生考试公告（中高考相关）",
    ),
    EducationPreset(
        key="beijing-bjedu",
        label="北京教委工会 · 通知",
        aliases=("北京教委工会", "bjedu"),
        track=EduTrack.K12,
        facet="city",
        fetch_url="/gov/beijing/bjedu/gh",
        kind="region",
    ),
    EducationPreset(
        key="guangdong-edu",
        label="广东省教育厅 · 通知公告",
        aliases=("广东", "广东省", "guangdong", "粤", "广东教育厅"),
        track=EduTrack.K12,
        facet="city",
        fetch_url="/gov/guangdong/edu/tzgg",
        kind="region",
    ),
    EducationPreset(
        key="guangdong-eea",
        label="广东省教育考试院 · 考试招生",
        aliases=("广东考试院", "广东招考", "粤考院"),
        track=EduTrack.K12,
        facet="city",
        fetch_url="/gov/guangdong/eea/kszs",
        kind="region",
    ),
    EducationPreset(
        key="jiangsu-eea",
        label="江苏教育考试院 · 招考要闻",
        aliases=("江苏", "江苏省", "jiangsu", "苏", "江苏考试院", "jseea"),
        track=EduTrack.K12,
        facet="city",
        fetch_url="/gov/jiangsu/eea/zkyw",
        kind="region",
    ),
)

# --- 考研: national (研招网直连) + key universities as watch subscriptions ---
KAOYAN_NATIONAL_PRESETS: tuple[EducationPreset, ...] = (
    EducationPreset(
        key="chsi-zcdh",
        label="研招网 · 政策导航",
        aliases=("研招网", "考研政策", "chsi", "中国研究生招生信息网", "国家政策"),
        track=EduTrack.KAOYAN,
        facet="national",
        fetch_url="https://yz.chsi.com.cn/kyzx/zcdh/",
        kind="national",
    ),
    EducationPreset(
        key="chsi-kydt",
        label="研招网 · 考研动态",
        aliases=("考研动态", "kydt"),
        track=EduTrack.KAOYAN,
        facet="national",
        fetch_url="https://yz.chsi.com.cn/kyzx/kydt/",
        kind="national",
    ),
    EducationPreset(
        key="chsi-hotnews",
        label="研招网 · 热点/动态",
        aliases=("考研热点", "hotnews"),
        track=EduTrack.KAOYAN,
        facet="national",
        fetch_url="https://yz.chsi.com.cn/kyzx/kydt/",
        kind="national",
    ),
    EducationPreset(
        key="chsi-fstj",
        label="研招网 · 复试调剂",
        aliases=("复试", "调剂", "分数线", "fstj"),
        track=EduTrack.KAOYAN,
        facet="score",
        fetch_url="https://yz.chsi.com.cn/kyzx/fstj/",
        kind="national",
    ),
)

KAOYAN_SCHOOL_PRESETS: tuple[EducationPreset, ...] = (
    EducationPreset(
        key="pku",
        label="北大 · 考研关注",
        aliases=("北大", "北京大学", "pku", "peking"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:北京大学",
        kind="school",
        note="研招网标题含校名时收录",
    ),
    EducationPreset(
        key="sjtu",
        label="上交 · 考研关注",
        aliases=("上交", "上海交大", "上海交通大学", "sjtu"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:上海交通大学",
        kind="school",
    ),
    EducationPreset(
        key="zju",
        label="浙大 · 考研关注",
        aliases=("浙大", "浙江大学", "zju"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:浙江大学",
        kind="school",
    ),
    EducationPreset(
        key="nju",
        label="南大 · 考研关注",
        aliases=("南大", "南京大学", "nju"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:南京大学",
        kind="school",
    ),
    EducationPreset(
        key="ustc",
        label="中科大 · 考研关注",
        aliases=("中科大", "中国科学技术大学", "ustc"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:中国科学技术大学",
        kind="school",
    ),
    EducationPreset(
        key="hit",
        label="哈工大 · 考研关注",
        aliases=("哈工大", "哈尔滨工业大学", "hit"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:哈尔滨工业大学",
        kind="school",
    ),
    EducationPreset(
        key="xjtu",
        label="西交 · 考研关注",
        aliases=("西交", "西安交大", "西安交通大学", "xjtu"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:西安交通大学",
        kind="school",
    ),
    EducationPreset(
        key="seu",
        label="东南 · 考研关注",
        aliases=("东南", "东南大学", "seu"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:东南大学",
        kind="school",
    ),
    EducationPreset(
        key="tju",
        label="天大 · 考研关注",
        aliases=("天大", "天津大学", "tju"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:天津大学",
        kind="school",
    ),
    EducationPreset(
        key="hust",
        label="华科 · 考研关注",
        aliases=("华科", "华中科技大学", "hust"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:华中科技大学",
        kind="school",
    ),
    EducationPreset(
        key="tongji",
        label="同济 · 考研关注",
        aliases=("同济", "同济大学", "tongji"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:同济大学",
        kind="school",
    ),
    EducationPreset(
        key="bit",
        label="北理工 · 考研关注",
        aliases=("北理", "北理工", "北京理工大学", "bit"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:北京理工大学",
        kind="school",
    ),
    EducationPreset(
        key="uestc",
        label="电子科大 · 考研关注",
        aliases=("成电", "电子科大", "电子科技大学", "uestc"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:电子科技大学",
        kind="school",
    ),
    EducationPreset(
        key="bjtu",
        label="北交大 · 考研关注",
        aliases=("北交大", "北京交通大学", "bjtu"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:北京交通大学",
        kind="school",
    ),
    EducationPreset(
        key="cuc",
        label="中传 · 考研关注",
        aliases=("中传", "中国传媒大学", "cuc"),
        track=EduTrack.KAOYAN,
        facet="prospectus",
        fetch_url="watch:kaoyan:中国传媒大学",
        kind="school",
    ),
)

ALL_PRESETS: tuple[EducationPreset, ...] = (
    *K12_REGION_PRESETS,
    *KAOYAN_NATIONAL_PRESETS,
    *KAOYAN_SCHOOL_PRESETS,
)

_KIND_GROUPS: dict[str, tuple[EducationPreset, ...]] = {
    "k12_region": K12_REGION_PRESETS,
    "region": K12_REGION_PRESETS,
    "kaoyan_school": (*KAOYAN_NATIONAL_PRESETS, *KAOYAN_SCHOOL_PRESETS),
    "school": KAOYAN_SCHOOL_PRESETS,
    "kaoyan": (*KAOYAN_NATIONAL_PRESETS, *KAOYAN_SCHOOL_PRESETS),
}


def list_presets(kind: str | None = None) -> list[EducationPreset]:
    if not kind:
        return list(ALL_PRESETS)
    return list(_KIND_GROUPS.get((kind or "").strip().lower(), ()))


def suggest_labels(kind: str) -> list[str]:
    """Primary aliases for datalist autocomplete."""
    seen: set[str] = set()
    out: list[str] = []
    for p in list_presets(kind):
        # Prefer short Chinese alias first.
        primary = p.aliases[0] if p.aliases else p.label
        if primary not in seen:
            seen.add(primary)
            out.append(primary)
    return out


def _norm_query(raw: str) -> str:
    return (raw or "").strip().lower().replace("大学", "").replace(" ", "")


def resolve_presets(query: str, *, kind: str) -> tuple[list[EducationPreset], list[str]]:
    """Resolve user input (comma/space separated) → matched presets + unmatched tokens."""
    tokens = [
        t.strip()
        for part in (query or "").replace("，", ",").replace("、", ",").split(",")
        for t in part.split()
        if t.strip()
    ]
    if not tokens:
        return [], []

    pool = list_presets(kind)
    matched: list[EducationPreset] = []
    seen_keys: set[str] = set()
    unmatched: list[str] = []

    for token in tokens:
        hits = _match_token(token, pool)
        if not hits:
            unmatched.append(token)
            continue
        for hit in hits:
            if hit.key not in seen_keys:
                seen_keys.add(hit.key)
                matched.append(hit)
    return matched, unmatched


def _match_token(token: str, pool: list[EducationPreset]) -> list[EducationPreset]:
    q = _norm_query(token)
    if not q:
        return []
    exact: list[EducationPreset] = []
    fuzzy: list[EducationPreset] = []
    for p in pool:
        alias_norms = {_norm_query(a) for a in p.aliases} | {_norm_query(p.label), p.key}
        if q in alias_norms or token.strip() in p.aliases or token.strip() == p.label:
            exact.append(p)
            continue
        if any(q in a or a in q for a in alias_norms if a):
            fuzzy.append(p)
    return exact or fuzzy


def preset_catalog_for_ui() -> dict[str, list[dict]]:
    """Grouped catalog for settings <details>."""
    def _rows(items: tuple[EducationPreset, ...]) -> list[dict]:
        return [
            {
                "key": p.key,
                "label": p.label,
                "aliases": " / ".join(p.aliases[:4]),
                "fetch_url": p.fetch_url,
                "facet": p.facet,
                "note": p.note,
            }
            for p in items
        ]

    return {
        "k12_regions": _rows(K12_REGION_PRESETS),
        "kaoyan_national": _rows(KAOYAN_NATIONAL_PRESETS),
        "kaoyan_schools": _rows(KAOYAN_SCHOOL_PRESETS),
    }
