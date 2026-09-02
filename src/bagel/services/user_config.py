"""Per-user config overlays on top of system .env defaults.

Unconfigured keys fall back to `.env` / live Settings. User saves write only
to `data/user_config/<user_id>.json` and never mutate shared `.env`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from bagel.services import env_config as env_cfg
from bagel.settings import get_settings

_lock = threading.RLock()

# Keys that remain process-wide (admin edits shared .env). Everyone else only
# stores personal overrides for the remaining catalog keys.
SYSTEM_ENV_KEYS: frozenset[str] = frozenset(
    {
        "APP_ENV",
        "APP_HOST",
        "APP_PORT",
        "LOG_LEVEL",
        "AUTH_REQUIRED",
        "SESSION_SECRET",
        "STORAGE_BACKEND",
        "DATABASE_URL",
        "ENABLE_SCHEDULER",
        "SCHEDULER_JITTER_SECONDS",
    }
)


def _user_config_dir() -> Path:
    root = Path(get_settings().data_dir)
    path = root / "user_config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_path(user_id: UUID | str) -> Path:
    return _user_config_dir() / f"{user_id}.json"


def load_user_overrides(user_id: UUID | str | None) -> dict[str, str]:
    if not user_id:
        return {}
    path = user_config_path(user_id)
    if not path.exists():
        return {}
    with _lock:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def save_user_overrides(user_id: UUID | str, updates: dict[str, str]) -> Path:
    """Merge ``updates`` into the user's overlay (empty string clears override)."""
    allowed = {f.key for f in env_cfg.ENV_CATALOG} - SYSTEM_ENV_KEYS
    path = user_config_path(user_id)
    with _lock:
        current = load_user_overrides(user_id)
        for key, value in updates.items():
            if key not in allowed:
                continue
            text = (value if value is not None else "").strip()
            field = next((f for f in env_cfg.ENV_CATALOG if f.key == key), None)
            if field is None:
                continue
            # Keep existing secret when UI posts masked placeholder.
            if field.type == "secret":
                existing = current.get(key) or env_cfg.read_env_map().get(key) or ""
                if not text or text.startswith("••••") or text == env_cfg._mask(existing):
                    continue
            if field.type == "bool":
                text = "true" if text.lower() in {"1", "true", "on", "yes"} else "false"
            elif field.type == "int":
                if text == "":
                    current.pop(key, None)
                    continue
                try:
                    int(text)
                except ValueError as exc:
                    raise env_cfg.EnvConfigError(f"{key} 必须是整数") from exc
            elif field.type == "select" and field.options and text and text not in field.options:
                raise env_cfg.EnvConfigError(f"{key} 必须是 {', '.join(field.options)} 之一")
            if text == "":
                current.pop(key, None)
            else:
                from bagel.pipeline.paths import portable_env_value

                current[key] = portable_env_value(key, text) if text else text
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def defaults_map() -> dict[str, str]:
    file_vals = env_cfg.read_env_map()
    fallback = env_cfg.current_settings_fallback()
    out = dict(fallback)
    out.update(file_vals)
    return out


def merged_config_for_user(user_id: UUID | str | None) -> dict[str, str]:
    """System defaults with per-user overrides on top."""
    merged = defaults_map()
    merged.update(load_user_overrides(user_id))
    return merged


def catalog_for_ui(user_id: UUID | str | None = None, *, is_admin: bool = False) -> list[dict[str, Any]]:
    from bagel.pipeline.paths import portable_env_value

    defaults = defaults_map()
    overrides = load_user_overrides(user_id)
    groups: dict[str, list[dict[str, Any]]] = {}
    for field in env_cfg.ENV_CATALOG:
        is_system = field.key in SYSTEM_ENV_KEYS
        if is_system and not is_admin:
            # Non-admins still see effective value (read-only) for awareness.
            pass
        if field.key in overrides:
            raw = overrides[field.key]
            source = "user"
        else:
            raw = defaults.get(field.key, "")
            source = "default"
        if field.type != "secret" and raw:
            raw = portable_env_value(field.key, raw)
        display = raw
        if field.type == "secret" and raw:
            display = env_cfg._mask(raw)
        groups.setdefault(field.group, []).append(
            {
                "key": field.key,
                "label": field.label,
                "type": field.type,
                "help": field.help,
                "options": list(field.options),
                "restart_hint": field.restart_hint and is_system,
                "value": raw,
                "display": display,
                "has_secret": bool(field.type == "secret" and raw),
                "source": source,
                "is_system": is_system,
                "readonly": is_system and not is_admin,
            }
        )
    return [{"group": g, "fields": fields} for g, fields in groups.items()]
