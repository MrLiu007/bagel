"""Lightweight dedup helpers (canonical URL + title hash).

Production upsert uses repository uniqueness constraints; this module is a
thin re-export for tests and ad-hoc checks.
"""

from __future__ import annotations

from bagel.storage.repositories import canonicalize_url, content_hash, normalize_title

__all__ = ["canonicalize_url", "content_hash", "normalize_title", "is_duplicate"]


def is_duplicate(
    *,
    url: str,
    title: str,
    existing_canonical_urls: set[str],
    existing_hashes: set[str],
) -> bool:
    canonical = canonicalize_url(url)
    digest = content_hash(canonical, title)
    return canonical in existing_canonical_urls or digest in existing_hashes
