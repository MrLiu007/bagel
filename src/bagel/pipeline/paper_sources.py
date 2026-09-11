"""Map paper IntelSource rows → family buckets for UI filter tabs.

arXiv cs.AI / cs.LG / … all collapse to one「arXiv」tab.
"""

from __future__ import annotations

from dataclasses import dataclass

# (key, display label, match needles against "name url" lowercased)
_FAMILY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("arxiv", "arXiv", ("arxiv",)),
    # Kept for any leftover manual HF paper rows; defaults no longer seed them.
    ("hf", "Hugging Face", ("huggingface", "hf papers", "hf:")),
    ("openalex", "OpenAlex", ("openalex",)),
    ("s2", "Semantic Scholar", ("semantic scholar", "semanticscholar", "s2:")),
)


@dataclass(frozen=True)
class PaperSourceFamily:
    key: str
    label: str


def family_for_source(*, name: str, url: str = "") -> PaperSourceFamily:
    blob = f"{name} {url}".lower()
    for key, label, needles in _FAMILY_RULES:
        if any(n in blob for n in needles):
            return PaperSourceFamily(key=key, label=label)
    raw = (name or "其他").split("·")[0].split("—")[0].strip() or "其他"
    key = "".join(ch if ch.isalnum() else "-" for ch in raw.lower()).strip("-")[:32] or "other"
    return PaperSourceFamily(key=key, label=raw[:32])
