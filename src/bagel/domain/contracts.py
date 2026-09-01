"""Shared domain contracts / DTOs exchanged between collectors and storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NormalizedItem(BaseModel):
    """Collector → pipeline intermediate contract.

    Collectors must emit this shape; repositories persist it as `IntelItem`
    plus optional `IntelRawEvidence`. LLM summaries live on the item row only
    and must never replace `raw_payload`.
    """

    item_type: str
    source_type: str
    source_id: UUID | None = None
    title: str
    summary: str | None = None
    content: str | None = None
    url: str
    canonical_url: str
    author: str | None = None
    language: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
