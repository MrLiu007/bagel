"""Per-kind default brief prompts (user overrides) stored in data/brief_prompts.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from bagel.domain.enums import BriefKind
from bagel.services import prompts as prompt_defs
from bagel.settings import get_settings

_lock = threading.RLock()

_SYSTEM_BY_KIND: dict[str, str] = {
    BriefKind.NEWS: prompt_defs.MONTHLY_BRIEF_SYSTEM_NEWS,
    BriefKind.GITHUB: prompt_defs.MONTHLY_BRIEF_SYSTEM_GITHUB,
    BriefKind.SCIENCE: prompt_defs.MONTHLY_BRIEF_SYSTEM_SCIENCE,
    BriefKind.EDUCATION: prompt_defs.MONTHLY_BRIEF_SYSTEM_EDUCATION,
    BriefKind.MODEL: prompt_defs.MONTHLY_BRIEF_SYSTEM_MODEL,
    BriefKind.MEDIA: prompt_defs.MONTHLY_BRIEF_SYSTEM_MEDIA,
    BriefKind.STOCK: prompt_defs.MONTHLY_BRIEF_SYSTEM_STOCK,
}


def prompts_path() -> Path:
    root = Path(get_settings().data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "brief_prompts.json"


def load_all_defaults() -> dict[str, str]:
    path = prompts_path()
    with _lock:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if v}


def load_default(kind: str) -> str:
    return load_all_defaults().get(kind, "")


def save_default(kind: str, prompt: str) -> None:
    data = load_all_defaults()
    cleaned = (prompt or "").strip()
    if cleaned:
        data[kind] = cleaned
    elif kind in data:
        del data[kind]
    path = prompts_path()
    with _lock:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def system_prompt(kind: str) -> str:
    return _SYSTEM_BY_KIND.get(kind, prompt_defs.MONTHLY_BRIEF_SYSTEM)


def resolve_prompt_used(kind: str, user_prompt: str | None) -> tuple[str, str, str]:
    """Return (user_prompt, system_prompt, display_prompt_used)."""
    user = (user_prompt or load_default(kind) or "").strip()
    system = system_prompt(kind)
    if user:
        display = f"【用户自定义】\n{user}\n\n【系统默认参考】\n{system}"
    else:
        display = f"【系统默认】\n{system}"
    return user, system, display
