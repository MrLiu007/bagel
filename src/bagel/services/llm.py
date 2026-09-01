"""LLM client — OpenAI-compatible chat completions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from bagel.domain.enums import ErrorCode
from bagel.domain.models import IntelItem
from bagel.integrations.http import build_http_client
from bagel.services.prompts import (
    SUMMARY_PROMPT_VERSION,
    SUMMARY_SYSTEM,
    SUMMARY_USER_TEMPLATE,
)
from bagel.settings import Settings, get_settings


@dataclass
class SummaryResult:
    summary: str = ""
    why: str = ""
    audience: str = ""
    title_zh: str = ""
    prompt_version: str = SUMMARY_PROMPT_VERSION
    raw_response: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


class LlmClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        s = self.settings
        return bool(
            s.llm_enabled
            and s.enable_llm_summary
            and s.llm_base_url
            and s.llm_model
        )

    def summarize_item(self, item: IntelItem) -> SummaryResult:
        if not self.available:
            return SummaryResult(
                error_code=ErrorCode.LLM_ERROR,
                error_message="LLM is not configured or disabled",
            )

        body = (item.content or item.summary or "")[:4000]
        user = SUMMARY_USER_TEMPLATE.format(
            title=item.title,
            url=item.url,
            source_type=item.source_type,
            published_at=item.published_at or "",
            body=body or "(无正文)",
        )
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        timeout = float(getattr(self.settings, "llm_timeout_seconds", 180) or 180)
        try:
            with build_http_client(self.settings, timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            return SummaryResult(
                error_code=ErrorCode.LLM_ERROR,
                error_message=str(exc)[:500],
            )

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        parsed = _parse_json_object(content)
        if parsed is None:
            return SummaryResult(
                summary=content[:150],
                title_zh=item.title,
                raw_response=data,
                error_code=ErrorCode.LLM_ERROR,
                error_message="LLM response was not valid JSON",
            )
        return SummaryResult(
            summary=str(parsed.get("summary") or "")[:300],
            why=str(parsed.get("why") or "")[:300],
            audience=str(parsed.get("audience") or "")[:120],
            title_zh=str(parsed.get("title_zh") or item.title)[:200],
            raw_response=data,
        )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
