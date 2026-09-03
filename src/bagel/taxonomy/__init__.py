"""Bagel domain taxonomy — structure inspired by os-taxonomy, content is Bagel's own.

Pure data + loader. Not Marble curriculum. Used by wiki compile and GBrain.
"""

from __future__ import annotations

from bagel.taxonomy.loader import (
    Taxonomy,
    children_of,
    clear_taxonomy_cache,
    get_taxonomy,
    load_taxonomy,
    match_topics,
    topic_by_category,
    validate_taxonomy,
)
from bagel.taxonomy.models import Cluster, Dependency, Topic

__all__ = [
    "Cluster",
    "Dependency",
    "Taxonomy",
    "Topic",
    "children_of",
    "clear_taxonomy_cache",
    "get_taxonomy",
    "load_taxonomy",
    "match_topics",
    "topic_by_category",
    "validate_taxonomy",
]
