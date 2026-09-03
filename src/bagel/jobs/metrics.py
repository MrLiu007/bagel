"""Shared per-source / duration metrics for collect job results."""

from __future__ import annotations

from typing import Any


def source_stat(
    name: str,
    *,
    status: str,
    items_found: int = 0,
    items_created: int = 0,
    items_updated: int = 0,
    items_skipped: int = 0,
    duration_ms: int = 0,
    error: str | None = None,
    region: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """One row for the task-detail sources table."""
    row: dict[str, Any] = {
        "name": name,
        "status": status,  # success | failed | skipped
        "items_found": int(items_found),
        "items_created": int(items_created),
        "items_updated": int(items_updated),
        "items_skipped": int(items_skipped),
        "duration_ms": max(0, int(duration_ms)),
    }
    if region:
        row["region"] = region
    if source_id:
        row["source_id"] = source_id
    if error:
        row["error"] = str(error)[:300]
    return row


def elapsed_ms(started: float, ended: float | None = None) -> int:
    import time

    end = time.perf_counter() if ended is None else ended
    return max(0, int((end - started) * 1000))
