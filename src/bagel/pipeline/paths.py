"""Portable path helpers — never surface machine-absolute paths in UI/logs."""

from __future__ import annotations

import re
from pathlib import Path

# Env keys that store filesystem paths (normalize for UI + .env writes).
PATH_ENV_KEYS = frozenset(
    {
        "MEDIA_CRAWLER_PATH",
        "WIKI_DIR",
        "FEISHU_CLI_BIN",
        "DATA_DIR",
    }
)

_SQLITE_FILE_RE = re.compile(
    r"^(sqlite(?:\+[a-z0-9]+)?:///?)(.+)$",
    re.IGNORECASE,
)
_WIN_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


def project_root() -> Path:
    """Bagel repo root (parent of src/)."""
    # this file: src/bagel/pipeline/paths.py
    return Path(__file__).resolve().parents[3]


def is_absolute_fs_path(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.startswith(("/", "\\")):
        return True
    if _WIN_ABS_RE.match(s):
        return True
    try:
        return Path(s).is_absolute()
    except (TypeError, ValueError, OSError):
        return False


def display_path(path: str | Path | None, *, fallback: str = "—") -> str:
    """Return a project-relative POSIX-ish path for UI / user messages.

    Examples:
      D:\\coder\\…\\ai-bagel\\.env  →  .env
      /abs/…/ai-bagel/data/x       →  data/x
      ./third_party/MediaCrawler          →  third_party/MediaCrawler
    """
    if path is None:
        return fallback
    text = str(path).strip()
    if not text:
        return fallback

    try:
        p = Path(text).expanduser()
    except (TypeError, ValueError, OSError):
        return text.replace("\\", "/")

    root = project_root()
    try:
        resolved = p if p.is_absolute() else (Path.cwd() / p)
        try:
            resolved = resolved.resolve()
        except OSError:
            pass
        try:
            rel = resolved.relative_to(root.resolve())
            out = rel.as_posix()
            return out if out not in {".", ""} else "."
        except ValueError:
            # Outside project — show only last 2 parts to avoid leaking home dirs
            parts = resolved.parts
            if len(parts) >= 2:
                return f"…/{parts[-2]}/{parts[-1]}".replace("\\", "/")
            return resolved.name or fallback
    except (OSError, RuntimeError, ValueError):
        return text.replace("\\", "/")


def to_portable(path: str | Path | None) -> str:
    """Prefer project-relative path with forward slashes for .env / config storage."""
    if path is None:
        return ""
    text = str(path).strip()
    if not text:
        return ""
    # Bare command names (e.g. lark-cli) stay as-is
    if "/" not in text and "\\" not in text and not _WIN_ABS_RE.match(text):
        return text
    if not is_absolute_fs_path(text):
        return text.replace("\\", "/")

    try:
        resolved = Path(text).expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:
            pass
        rel = resolved.relative_to(project_root().resolve())
        out = rel.as_posix()
        return "." if out in {".", ""} else out
    except (ValueError, OSError, RuntimeError):
        # Outside project: keep as given but normalize separators (caller may still want abs)
        return text.replace("\\", "/")


def portable_env_value(key: str, value: str) -> str:
    """Normalize path-like env values for display / rewrite."""
    text = (value or "").strip()
    if not text:
        return text

    if key == "DATABASE_URL":
        m = _SQLITE_FILE_RE.match(text)
        if m:
            prefix, file_part = m.group(1), m.group(2)
            # Memory / empty
            if file_part in {":memory:", ""}:
                return text
            # URL form sqlite:///./data/x.db — keep relative; rewrite abs under project
            if is_absolute_fs_path(file_part) or file_part.startswith("//"):
                # sqlite:////abs or sqlite:///D:/...
                raw = file_part[1:] if file_part.startswith("//") else file_part
                port = to_portable(raw)
                if port and not is_absolute_fs_path(port):
                    # sqlalchemy relative file URLs use sqlite:///./path
                    rel = port if port.startswith(".") else f"./{port}"
                    return f"sqlite+pysqlite:///{rel}" if "+" in prefix else f"sqlite:///{rel}"
            return text.replace("\\", "/")
        return text

    if key in PATH_ENV_KEYS or key.endswith("_PATH") or key.endswith("_DIR"):
        return to_portable(text) if is_absolute_fs_path(text) else text.replace("\\", "/")

    return text
