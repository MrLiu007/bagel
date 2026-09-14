"""Education channel tracks: 公开课 / K12 / 考研.

Track + optional facet are encoded on ``IntelSource.url`` as::

    edu:{track}:{facet}:{fetch_url}
    edu:{track}:{fetch_url}

Plain ``https://…`` / ``/rsshub/…`` URLs stay valid for open-course OCW seeds.
K12 / 考研 sources without a prefix are still classified via name / URL heuristics
so mis-seeded rows do not land under 公开课.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EduTrack(StrEnum):
    OPEN_COURSE = "open_course"
    K12 = "k12"
    KAOYAN = "kaoyan"


class EduFacet(StrEnum):
    """Secondary filter within a track (not used for open_course school tabs)."""

    NATIONAL = "national"
    CITY = "city"
    REFORM = "reform"
    PROSPECTUS = "prospectus"
    SYLLABUS = "syllabus"
    SCORE = "score"


TRACK_LABELS: dict[EduTrack, str] = {
    EduTrack.OPEN_COURSE: "公开课",
    EduTrack.K12: "K12",
    EduTrack.KAOYAN: "考研",
}

TRACK_TABS: tuple[tuple[EduTrack, str], ...] = (
    (EduTrack.OPEN_COURSE, "公开课"),
    (EduTrack.K12, "K12"),
    (EduTrack.KAOYAN, "考研"),
)

K12_FACET_TABS: tuple[tuple[str, str], ...] = (
    ("", "全部"),
    (EduFacet.NATIONAL, "国家政策"),
    (EduFacet.CITY, "城市政策"),
    (EduFacet.REFORM, "改革新闻"),
)

KAOYAN_FACET_TABS: tuple[tuple[str, str], ...] = (
    ("", "全部"),
    (EduFacet.NATIONAL, "国家政策"),
    (EduFacet.PROSPECTUS, "招生简章"),
    (EduFacet.SYLLABUS, "考试大纲"),
    (EduFacet.SCORE, "分数线/调剂"),
)

_FACETS_BY_TRACK: dict[EduTrack, frozenset[str]] = {
    EduTrack.K12: frozenset({EduFacet.NATIONAL, EduFacet.CITY, EduFacet.REFORM}),
    EduTrack.KAOYAN: frozenset(
        {EduFacet.NATIONAL, EduFacet.PROSPECTUS, EduFacet.SYLLABUS, EduFacet.SCORE}
    ),
    EduTrack.OPEN_COURSE: frozenset(),
}

_VALID_TRACKS = frozenset(t.value for t in EduTrack)

# Fetch-URL needles → (track, default facet). Longer / more specific first.
_FETCH_TRACK_RULES: tuple[tuple[str, EduTrack, str], ...] = (
    ("watch:kaoyan:", EduTrack.KAOYAN, EduFacet.PROSPECTUS),
    ("watch:k12:", EduTrack.K12, EduFacet.CITY),
    ("/gov/moe/policy_anal", EduTrack.K12, EduFacet.REFORM),
    ("/gov/moe/edu_focus_news", EduTrack.K12, EduFacet.REFORM),
    ("/gov/moe/", EduTrack.K12, EduFacet.NATIONAL),
    ("moe.gov.cn", EduTrack.K12, EduFacet.NATIONAL),
    ("/gov/beijing/bjedu", EduTrack.K12, EduFacet.CITY),
    ("jw.beijing.gov.cn", EduTrack.K12, EduFacet.CITY),
    ("yz.chsi.com.cn", EduTrack.KAOYAN, EduFacet.NATIONAL),
    ("chsi.com.cn/ky", EduTrack.KAOYAN, EduFacet.NATIONAL),
    ("yz.tsinghua.edu.cn", EduTrack.KAOYAN, EduFacet.PROSPECTUS),
    ("admission.pku.edu.cn", EduTrack.KAOYAN, EduFacet.PROSPECTUS),
    ("graduate.", EduTrack.KAOYAN, EduFacet.PROSPECTUS),
    ("yjsy.", EduTrack.KAOYAN, EduFacet.PROSPECTUS),
    ("研招网", EduTrack.KAOYAN, EduFacet.NATIONAL),
)

# Name needles → track (checked before open-course default).
_NAME_KAOYAN = (
    "考研",
    "研招",
    "研究生招生",
    "招生简章",
    "专业目录",
    "考试大纲",
    "国家线",
    "调剂",
)
_NAME_K12 = (
    "教育部",
    "教委",
    "教育局",
    "k12",
    "义务教育",
    "基础教育",
    "双减",
    "中小学",
    "学前教育",
    "课后服务",
    "学区",
)


@dataclass(frozen=True)
class ParsedEducationSource:
    track: EduTrack
    facet: str | None
    fetch_url: str
    stored_url: str


def normalize_track(raw: str | None) -> EduTrack:
    key = (raw or "").strip().lower().replace("-", "_")
    if key in {"ocw", "mooc", "open", "opencourse", "公开课"}:
        return EduTrack.OPEN_COURSE
    if key in {"k12", "basic", "基础"}:
        return EduTrack.K12
    if key in {"kaoyan", "postgrad", "考研", "研究生"}:
        return EduTrack.KAOYAN
    if key in _VALID_TRACKS:
        return EduTrack(key)
    return EduTrack.OPEN_COURSE


def normalize_facet(track: EduTrack, raw: str | None) -> str | None:
    key = (raw or "").strip().lower()
    if not key:
        return None
    allowed = _FACETS_BY_TRACK.get(track, frozenset())
    return key if key in allowed else None


def parse_education_url(url: str | None) -> ParsedEducationSource:
    stored = (url or "").strip()
    if not stored.lower().startswith("edu:"):
        return ParsedEducationSource(
            track=EduTrack.OPEN_COURSE,
            facet=None,
            fetch_url=stored,
            stored_url=stored,
        )
    body = stored[4:]
    track_raw, sep, rem = body.partition(":")
    track = normalize_track(track_raw)
    if not sep:
        return ParsedEducationSource(track=track, facet=None, fetch_url="", stored_url=stored)
    # rem is either "https://…", "/path", or "{facet}:{payload}"
    if (
        rem.startswith("http")
        or rem.startswith("/")
        or rem.startswith("av:")
        or rem.lower().startswith("watch:")
    ):
        return ParsedEducationSource(
            track=track, facet=None, fetch_url=rem.strip(), stored_url=stored
        )
    facet_raw, sep2, payload = rem.partition(":")
    facet = normalize_facet(track, facet_raw)
    if facet and sep2 and payload.strip():
        return ParsedEducationSource(
            track=track,
            facet=facet,
            fetch_url=payload.strip(),
            stored_url=stored,
        )
    # Unknown second segment — treat whole rem as fetch URL.
    return ParsedEducationSource(
        track=track, facet=None, fetch_url=rem.strip(), stored_url=stored
    )


def build_education_url(
    fetch_url: str,
    *,
    track: EduTrack | str = EduTrack.OPEN_COURSE,
    facet: str | None = None,
) -> str:
    """Build stored URL. Open-course plain http(s)/path stays unprefixed."""
    cleaned = (fetch_url or "").strip()
    if cleaned.lower().startswith("edu:"):
        parsed = parse_education_url(cleaned)
        cleaned = parsed.fetch_url
        if track == EduTrack.OPEN_COURSE and not facet:
            track = parsed.track
            facet = parsed.facet
    track_v = normalize_track(str(track))
    facet_v = normalize_facet(track_v, facet)
    if track_v == EduTrack.OPEN_COURSE and not facet_v:
        return cleaned
    if facet_v:
        return f"edu:{track_v.value}:{facet_v}:{cleaned}"
    return f"edu:{track_v.value}:{cleaned}"


def _infer_track_facet(name: str, fetch_url: str) -> tuple[EduTrack, str | None]:
    blob = f"{name} {fetch_url}".lower()
    fetch_l = (fetch_url or "").lower()

    for needle, track, facet in _FETCH_TRACK_RULES:
        if needle.lower() in fetch_l or needle.lower() in blob:
            # Name can override facet within same track family.
            if track == EduTrack.KAOYAN:
                return EduTrack.KAOYAN, _infer_kaoyan_facet(blob, facet)
            if track == EduTrack.K12:
                return EduTrack.K12, _infer_k12_facet(blob, facet)
            return track, facet

    if any(k in blob for k in _NAME_KAOYAN):
        return EduTrack.KAOYAN, _infer_kaoyan_facet(blob, EduFacet.NATIONAL)
    if any(k in blob for k in _NAME_K12):
        return EduTrack.K12, _infer_k12_facet(blob, EduFacet.NATIONAL)
    return EduTrack.OPEN_COURSE, None


def _infer_k12_facet(blob: str, default: str) -> str:
    if any(k in blob for k in ("教委", "教育局", "beijing", "上海", "广州", "深圳", "杭州", "城市")):
        return EduFacet.CITY
    if any(k in blob for k in ("解读", "改革", "focus", "policy_anal", "教育报", "人民网", "聚焦")):
        return EduFacet.REFORM
    return default


def _infer_kaoyan_facet(blob: str, default: str) -> str:
    if any(k in blob for k in ("大纲", "syllabus", "参考书")):
        return EduFacet.SYLLABUS
    if any(k in blob for k in ("分数线", "调剂", "复试", "国家线")):
        return EduFacet.SCORE
    if any(k in blob for k in ("简章", "专业目录", "prospectus", "招生章程")):
        return EduFacet.PROSPECTUS
    # 研招网 / 国家政策资讯 — keep national (do not treat bare「研招」as prospectus).
    if any(k in blob for k in ("研招网", "国家政策", "yz.chsi")):
        return EduFacet.NATIONAL
    if "研招" in blob and "简章" not in blob:
        return default
    return default


def track_for_source(*, name: str = "", url: str = "") -> EduTrack:
    parsed = parse_education_url(url)
    if parsed.stored_url.lower().startswith("edu:"):
        return parsed.track
    inferred, _facet = _infer_track_facet(name, parsed.fetch_url)
    return inferred


def facet_for_source(*, name: str = "", url: str = "") -> str | None:
    parsed = parse_education_url(url)
    if parsed.facet:
        return parsed.facet
    track = track_for_source(name=name, url=url)
    if track == EduTrack.OPEN_COURSE:
        return None
    _inferred_track, facet = _infer_track_facet(name, parsed.fetch_url)
    if facet:
        return facet
    if track == EduTrack.K12:
        return EduFacet.NATIONAL
    if track == EduTrack.KAOYAN:
        return EduFacet.NATIONAL
    return None


def facet_tabs_for_track(track: EduTrack) -> tuple[tuple[str, str], ...]:
    if track == EduTrack.K12:
        return K12_FACET_TABS
    if track == EduTrack.KAOYAN:
        return KAOYAN_FACET_TABS
    return (("", "全部"),)


def canonical_education_url(*, name: str = "", url: str = "") -> str:
    """Return preferred stored URL with track/facet prefix when needed."""
    parsed = parse_education_url(url)
    track = track_for_source(name=name, url=url)
    facet = facet_for_source(name=name, url=url)
    return build_education_url(parsed.fetch_url or parsed.stored_url, track=track, facet=facet)
