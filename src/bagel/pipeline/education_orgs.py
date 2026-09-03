"""Map education IntelSource rows → school / institution buckets for UI tabs."""

from __future__ import annotations

from dataclasses import dataclass

# (key, display label, match needles against "name url" lowercased)
_INSTITUTION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("mit", "MIT", ("mit", "ocw.mit")),
    ("stanford", "Stanford", ("stanford",)),
    ("harvard", "Harvard", ("harvard",)),
    ("yale", "Yale", ("yale", "oyc.yale")),
    ("berkeley", "UC Berkeley", ("berkeley", "bair")),
    ("cmu", "CMU", ("cmu", "carnegie mellon", "oli.cmu")),
    ("oxford", "Oxford", ("oxford", "ox.ac.uk")),
    ("cambridge", "Cambridge", ("cambridge", "cam.ac.uk")),
    ("tsinghua", "清华", ("清华", "xuetangx", "tsinghua")),
    ("pku", "北大", ("北大", "pku", "peking")),
    ("coursera", "Coursera", ("coursera",)),
    ("classcentral", "Class Central", ("classcentral", "class central")),
    ("edx", "edX", ("edx",)),
    ("khan", "Khan Academy", ("khan",)),
    ("fastai", "fast.ai", ("fast.ai", "fastai")),
    ("distill", "Distill", ("distill.pub", "distill")),
    ("lillian", "Lil'Log", ("lilianweng", "lil'log", "lillog")),
)


@dataclass(frozen=True)
class EducationInstitution:
    key: str
    label: str


def institution_for_source(*, name: str, url: str = "") -> EducationInstitution:
    blob = f"{name} {url}".lower()
    for key, label, needles in _INSTITUTION_RULES:
        if any(n in blob for n in needles):
            return EducationInstitution(key=key, label=label)
    # Fallback: first segment before · / — keeps unknown sources usable.
    raw = (name or "其他").split("·")[0].split("—")[0].strip() or "其他"
    key = "".join(ch if ch.isalnum() else "-" for ch in raw.lower()).strip("-")[:32] or "other"
    return EducationInstitution(key=key, label=raw[:24])
