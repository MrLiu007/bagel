"""Taxonomy dataclasses — nodes / edges / clusters (os-taxonomy-shaped)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TopicType = Literal[
    "CONCEPTUAL",
    "PROCEDURAL",
    "REPRESENTATIONAL",
    "LANGUAGE",
    "META",
]
EdgeStrength = Literal["hard", "soft"]


@dataclass(frozen=True, slots=True)
class Topic:
    """Micro-topic node (stable id, typed, alias-matchable)."""

    id: str
    type: TopicType
    subject: str
    name: str
    description: str
    domain: str | None = None
    aliases: tuple[str, ...] = ()
    category: str | None = None
    centrality: float = 0.0
    evidence: tuple[str, ...] = ()
    parent_id: str | None = None  # optional subtopic → parent micro-topic


@dataclass(frozen=True, slots=True)
class Dependency:
    """Directed prerequisite: topic_id depends on prerequisite_id."""

    topic_id: str
    prerequisite_id: str
    strength: EdgeStrength = "soft"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Cluster:
    """Parent-friendly domain summary for a subject/domain band."""

    id: str
    subject: str
    domain: str
    name: str
    summary: str
    topic_ids: tuple[str, ...] = ()
