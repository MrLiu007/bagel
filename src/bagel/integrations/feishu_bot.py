"""Feishu / Lark open-platform bot: event receive + OpenAPI reply.

Custom-bot webhooks are outbound-only. Inbound commands need an enterprise app
with event subscription pointing at POST /api/feishu/events.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from base64 import b64decode
from typing import Any

from bagel.integrations.http import build_http_client
from bagel.settings import get_settings
from bagel.storage.database import get_session_factory

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"token": "", "expire_at": 0.0}
_seen_events: dict[str, float] = {}
_SEEN_TTL = 600.0


class FeishuBotError(Exception):
    pass


def bot_configured() -> bool:
    s = get_settings()
    return bool((s.feishu_app_id or "").strip() and (s.feishu_app_secret or "").strip())


def verification_token() -> str:
    return (get_settings().feishu_verification_token or "").strip()


def encrypt_key() -> str:
    return (get_settings().feishu_encrypt_key or "").strip()


def decrypt_event_if_needed(payload: dict[str, Any]) -> dict[str, Any]:
    enc = payload.get("encrypt")
    if not enc:
        return payload
    key = encrypt_key()
    if not key:
        raise FeishuBotError("收到加密事件但未配置 FEISHU_ENCRYPT_KEY")
    plain = _decrypt_feishu(str(enc), key)
    data = json.loads(plain)
    if not isinstance(data, dict):
        raise FeishuBotError("解密后不是 JSON 对象")
    return data


def handle_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle URL challenge or schedule async message handling."""
    data = decrypt_event_if_needed(payload)

    if data.get("type") == "url_verification" or (
        data.get("challenge") and not data.get("header") and not data.get("event")
    ):
        token = verification_token()
        if token and data.get("token") and data.get("token") != token:
            raise FeishuBotError("verification token mismatch")
        return {"challenge": data.get("challenge")}

    token = verification_token()
    header = data.get("header") if isinstance(data.get("header"), dict) else {}
    event_token = header.get("token") or data.get("token")
    if token and event_token and event_token != token:
        raise FeishuBotError("event token mismatch")

    event_id = str(header.get("event_id") or data.get("uuid") or "")
    if event_id and _is_duplicate(event_id):
        return {"code": 0}

    event_type = str(header.get("event_type") or data.get("type") or "")
    event = data.get("event") if isinstance(data.get("event"), dict) else {}

    if event_type.startswith("im.message.receive") or isinstance(event.get("message"), dict):
        threading.Thread(
            target=_process_message_event,
            args=(event,),
            name="feishu-msg",
            daemon=True,
        ).start()
        return {"code": 0}

    return {"code": 0}


def reply_text(*, message_id: str | None, chat_id: str | None, text: str) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "empty"}

    if bot_configured() and message_id:
        try:
            return _openapi_reply(message_id, body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feishu.reply_failed fallback err=%s", exc)

    if bot_configured() and chat_id:
        try:
            return _openapi_send_chat(chat_id, body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feishu.send_chat_failed fallback err=%s", exc)

    from bagel.integrations import feishu_cli

    chunks = [body] if len(body) <= 3500 else _split(body, 3500)
    last: dict[str, Any] = {"ok": False}
    for chunk in chunks[:6]:
        result = feishu_cli.send_text(chunk)
        last = {"ok": result.ok, "error": result.error, "via": "webhook"}
        if not result.ok:
            break
    return last


def _process_message_event(event: dict[str, Any]) -> None:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    msg_type = str(message.get("message_type") or "")
    if msg_type and msg_type != "text":
        return
    content_raw = message.get("content") or "{}"
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except json.JSONDecodeError:
        content = {"text": str(content_raw)}
    text = str((content or {}).get("text") or "").strip()
    if not text:
        return

    message_id = str(message.get("message_id") or "") or None
    chat_id = str(message.get("chat_id") or "") or None

    factory = get_session_factory()
    session = factory()
    try:
        from bagel.services.feishu_command import handle_command

        result = handle_command(session, text)
        session.commit()
        chunks = result.chunks or [result.text]
        reply_text(message_id=message_id, chat_id=chat_id, text=chunks[0])
        for extra in chunks[1:6]:
            reply_text(message_id=None, chat_id=chat_id, text=extra)
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("feishu.process_message_failed")
        try:
            reply_text(
                message_id=message_id,
                chat_id=chat_id,
                text="处理指令失败，请稍后重试或发送「帮助」。",
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        session.close()


def get_tenant_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expire_at"] > now + 60:
        return str(_token_cache["token"])
    s = get_settings()
    app_id = (s.feishu_app_id or "").strip()
    app_secret = (s.feishu_app_secret or "").strip()
    if not app_id or not app_secret:
        raise FeishuBotError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
    with build_http_client(timeout=20.0) as client:
        resp = client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = resp.json()
    if data.get("code") != 0:
        raise FeishuBotError(f"token error: {data}")
    token = str(data.get("tenant_access_token") or "")
    expire = int(data.get("expire") or 7200)
    _token_cache["token"] = token
    _token_cache["expire_at"] = now + expire
    return token


def _openapi_reply(message_id: str, text: str) -> dict[str, Any]:
    token = get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
    with build_http_client(timeout=20.0) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        data = resp.json()
    if data.get("code") != 0:
        raise FeishuBotError(str(data))
    return {"ok": True, "via": "reply", "data": data.get("data")}


def _openapi_send_chat(chat_id: str, text: str) -> dict[str, Any]:
    token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    with build_http_client(timeout=20.0) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        data = resp.json()
    if data.get("code") != 0:
        raise FeishuBotError(str(data))
    return {"ok": True, "via": "chat", "data": data.get("data")}


def _is_duplicate(event_id: str) -> bool:
    now = time.time()
    stale = [k for k, t in _seen_events.items() if now - t > _SEEN_TTL]
    for k in stale:
        _seen_events.pop(k, None)
    if event_id in _seen_events:
        return True
    _seen_events[event_id] = now
    return False


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


def _decrypt_feishu(content: str, key: str) -> str:
    try:
        from Crypto.Cipher import AES  # type: ignore[import-untyped]
    except ImportError as exc:
        raise FeishuBotError(
            "事件已加密：请 pip install pycryptodome，或在飞书后台关闭加密（留空 Encrypt Key）"
        ) from exc
    raw = b64decode(content)
    iv, encrypted = raw[:16], raw[16:]
    cipher = AES.new(hashlib.sha256(key.encode("utf-8")).digest(), AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted)
    pad = decrypted[-1]
    decrypted = decrypted[:-pad] if isinstance(pad, int) else decrypted[: -ord(pad)]
    return decrypted.decode("utf-8")
