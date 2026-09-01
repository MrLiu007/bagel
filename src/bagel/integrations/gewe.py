"""Gewe WeChat HTTP client + keyword matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from bagel.settings import Settings, get_settings


class GeweError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass
class GeweStatus:
    enabled: bool
    configured: bool
    base_url: str
    has_token: bool
    has_app_id: bool
    callback_url: str
    keywords: list[str]


def status(settings: Settings | None = None) -> GeweStatus:
    settings = settings or get_settings()
    return GeweStatus(
        enabled=settings.wechat_active,
        configured=bool(settings.gewe_token and settings.gewe_app_id),
        base_url=settings.gewe_base_url,
        has_token=bool(settings.gewe_token),
        has_app_id=bool(settings.gewe_app_id),
        callback_url=settings.gewe_callback_url,
        keywords=settings.gewe_keyword_list,
    )


def keyword_hit(text: str, keywords: list[str] | None = None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    kws = keywords if keywords is not None else settings.gewe_keyword_list
    blob = text or ""
    if not kws:
        return True
    return any(k in blob for k in kws)


def extract_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize Gewe webhook / push payload into a flat message dict."""
    data = payload.get("Data") or payload.get("data") or payload
    if not isinstance(data, dict):
        return None
    content = (
        data.get("Content")
        or data.get("content")
        or data.get("text")
        or data.get("msg")
        or ""
    )
    if isinstance(content, dict):
        content = content.get("string") or content.get("text") or str(content)
    content = str(content).strip()
    if not content:
        return None
    from_user = str(data.get("FromUserName") or data.get("from_user") or data.get("sender") or "")
    msg_id = str(data.get("NewMsgId") or data.get("MsgId") or data.get("msg_id") or "")
    return {
        "content": content,
        "from_user": from_user,
        "msg_id": msg_id,
        "raw": data,
        "received_at": datetime.now(UTC).isoformat(),
    }


class GeweClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        if not self.settings.gewe_token:
            raise GeweError("GEWE_TOKEN 未配置")
        return {
            "X-GEWE-TOKEN": self.settings.gewe_token,
            "Content-Type": "application/json",
        }

    def check_online(self) -> dict[str, Any]:
        if not self.settings.gewe_app_id:
            raise GeweError("GEWE_APP_ID 未配置")
        url = f"{self.settings.gewe_base_url.rstrip('/')}/login/checkOnline"
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                url,
                headers=self._headers(),
                json={"appId": self.settings.gewe_app_id},
            )
            resp.raise_for_status()
            return resp.json()
