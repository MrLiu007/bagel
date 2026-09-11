"""Per-kind default brief prompts (user overrides) stored in data/brief_prompts.json."""

from __future__ import annotations

import json
import re
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
    BriefKind.AV: prompt_defs.MONTHLY_BRIEF_SYSTEM_AV,
    BriefKind.STOCK: prompt_defs.MONTHLY_BRIEF_SYSTEM_STOCK,
}

# Demo / test leftovers that must not pre-fill the custom-prompt box.
_LEGACY_DEMO_PROMPTS: frozenset[str] = frozenset(
    {
        "重点讲 LLM 推理成本",
        "重点讲LLM推理成本",
        "重点讲 LLM 推理成本。",
    }
)
_LEGACY_DEMO_RE = re.compile(r"^重点讲\s*LLM\s*推理成本[.。]?$", re.I)


def prompts_path() -> Path:
    root = Path(get_settings().data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "brief_prompts.json"


def _is_legacy_demo_prompt(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if cleaned in _LEGACY_DEMO_PROMPTS:
        return True
    return bool(_LEGACY_DEMO_RE.match(cleaned))


def _scrub_defaults(data: dict[str, str]) -> tuple[dict[str, str], bool]:
    out: dict[str, str] = {}
    changed = False
    for key, value in data.items():
        text = str(value).strip()
        if not text:
            changed = True
            continue
        if _is_legacy_demo_prompt(text):
            changed = True
            continue
        out[str(key)] = text
    return out, changed


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
        data = {str(k): str(v) for k, v in raw.items() if v}
        scrubbed, changed = _scrub_defaults(data)
        if changed:
            try:
                if scrubbed:
                    path.write_text(
                        json.dumps(scrubbed, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                else:
                    path.write_text("{}\n", encoding="utf-8")
            except OSError:
                pass
        return scrubbed


def load_default(kind: str) -> str:
    return load_all_defaults().get(kind, "")


def save_default(kind: str, prompt: str) -> None:
    data = load_all_defaults()
    cleaned = (prompt or "").strip()
    if cleaned and _is_legacy_demo_prompt(cleaned):
        # Never persist the old demo line as a type default.
        cleaned = ""
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
    """Return (explicit_user_prompt, system_prompt, display_prompt_used).

    Does **not** silently substitute saved defaults into the generation prompt —
    defaults only pre-fill the textarea. Pass the form value as ``user_prompt``.
    """
    user = (user_prompt or "").strip()
    system = system_prompt(kind)
    if user:
        display = f"【用户自定义】\n{user}\n\n【系统角色】\n{system}"
    else:
        display = f"【系统默认模板】\n{system}"
    return user, system, display


def load_prompt_for_form(kind: str) -> str:
    """Saved default for the custom-prompt textarea (may be empty)."""
    return load_default(kind)
