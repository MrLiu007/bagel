"""Archify adapter — render architecture JSON IR via Node CLI (no vendor of source)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from bagel.services.archify_setup import (
    default_target,
    is_checkout_ready,
    is_node_ready,
    node_bin,
    package_root,
)
from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.archify")


class ArchifyError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _resolve_root(settings: Settings) -> Path:
    raw = (settings.archify_path or "").strip() or "./third_party/archify"
    root = Path(raw)
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.enable_archify:
        return False
    if not is_node_ready():
        return False
    return is_checkout_ready(_resolve_root(settings))


def status_dict(settings: Settings | None = None) -> dict[str, Any]:
    from bagel.pipeline.paths import display_path

    settings = settings or get_settings()
    root = _resolve_root(settings)
    return {
        "enabled": settings.enable_archify,
        "node_ok": is_node_ready(),
        "checkout_ready": is_checkout_ready(root),
        "ready": is_configured(settings),
        "path": display_path(str(root)),
        "package": display_path(str(package_root(root))) if is_checkout_ready(root) else None,
    }


def sanitize_architecture_ir(ir: dict[str, Any], *, title: str = "Architecture") -> dict[str, Any]:
    """Normalize LLM/fallback IR to Archify architecture schema."""
    data = dict(ir or {})
    data.setdefault("schema_version", 1)
    data.setdefault("diagram_type", "architecture")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    data["meta"] = {
        "title": str(meta.get("title") or title)[:120],
        "quality_profile": str(meta.get("quality_profile") or "showcase"),
        "locale": str(meta.get("locale") or "zh-CN"),
    }
    allowed_types = {
        "frontend",
        "backend",
        "database",
        "cloud",
        "security",
        "messagebus",
        "external",
    }
    comps: list[dict[str, Any]] = []
    for i, c in enumerate(data.get("components") or []):
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type") or "backend")
        if ctype not in allowed_types:
            ctype = "backend"
        pos = c.get("pos") if isinstance(c.get("pos"), list) and len(c["pos"]) >= 2 else [40 + i * 40, 120]
        size = c.get("size") if isinstance(c.get("size"), list) and len(c["size"]) >= 2 else [140, 56]
        comps.append(
            {
                "id": str(c.get("id") or f"c{i}"),
                "type": ctype,
                "label": str(c.get("label") or f"Node {i}")[:40],
                "pos": [float(pos[0]), float(pos[1])],
                "size": [float(size[0]), float(size[1])],
                **({"sublabel": str(c["sublabel"])[:32]} if c.get("sublabel") else {}),
            }
        )
    data["components"] = comps or [
        {
            "id": "core",
            "type": "backend",
            "label": title.split("/")[-1][:28] or "Core",
            "pos": [260, 180],
            "size": [160, 64],
        }
    ]
    conns: list[dict[str, Any]] = []
    for i, c in enumerate(data.get("connections") or []):
        if not isinstance(c, dict) or not c.get("from") or not c.get("to"):
            continue
        conns.append(
            {
                "id": str(c.get("id") or f"e{i}"),
                "from": str(c["from"]),
                "to": str(c["to"]),
                **({"label": str(c["label"])[:24]} if c.get("label") else {}),
            }
        )
    data["connections"] = conns
    cards_in = data.get("cards")
    cards: list[dict[str, Any]] = []
    dots = ("cyan", "emerald", "rose", "amber", "orange", "pink")
    if isinstance(cards_in, list):
        for i, c in enumerate(cards_in):
            if not isinstance(c, dict):
                continue
            items = c.get("items")
            if not isinstance(items, list) or not items:
                body = c.get("body") or c.get("text")
                items = [str(body)] if body else []
            items = [str(x) for x in items if str(x).strip()][:8]
            if not items:
                continue
            cards.append(
                {
                    "dot": str(c.get("dot") or dots[i % len(dots)]),
                    "title": str(c.get("title") or "说明")[:80],
                    "items": items,
                }
            )
    data["cards"] = cards
    # Drop unknown top-level keys that may break validators.
    keep = {
        "schema_version",
        "diagram_type",
        "meta",
        "components",
        "connections",
        "boundaries",
        "cards",
    }
    return {k: v for k, v in data.items() if k in keep}


def deliver_architecture(
    ir: dict[str, Any],
    *,
    out_html: Path,
    settings: Settings | None = None,
    quality: str = "standard",
) -> dict[str, Any]:
    """Write IR JSON and run ``archify deliver architecture`` headlessly."""
    settings = settings or get_settings()
    if not is_configured(settings):
        raise ArchifyError(
            "Archify 未就绪：请安装 Node >= 18，然后重启 "
            "`uv run bagel dev`（启动时会自动 clone third_party/archify）"
        )
    root = _resolve_root(settings)
    pkg = package_root(root)
    node = node_bin()
    if not node:
        raise ArchifyError("未找到 node 可执行文件")

    # Absolute paths — Archify resolves inputs against cwd; relative paths break
    # when cwd is the npm package (seen as third_party/archify/archify/data/...).
    out_html = Path(out_html).resolve()
    out_html.parent.mkdir(parents=True, exist_ok=True)
    title = ""
    if isinstance(ir.get("meta"), dict):
        title = str(ir["meta"].get("title") or "")
    clean = sanitize_architecture_ir(ir, title=title or "Architecture")
    ir_path = out_html.with_suffix(".architecture.json")
    ir_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    from bagel.pipeline.paths import project_root

    qualities = [quality]
    if quality != "standard":
        qualities.append("standard")

    last_err = ""
    for q in qualities:
        cmd = [
            node,
            str((pkg / "bin" / "archify.mjs").resolve()),
            "deliver",
            "architecture",
            str(ir_path),
            str(out_html),
            "--quality",
            q,
            "--json",
        ]
        logger.info("archify.exec quality=%s input=%s", q, ir_path)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                cwd=str(project_root()),
            )
        except subprocess.TimeoutExpired as exc:
            raise ArchifyError("Archify deliver 超时") from exc
        except OSError as exc:
            raise ArchifyError(f"无法执行 Archify：{exc}") from exc

        if proc.returncode == 0 and out_html.is_file():
            return {
                "status": "done",
                "html_path": str(out_html),
                "ir_path": str(ir_path),
                "quality": q,
                "stdout": (proc.stdout or "")[:400],
            }
        last_err = (proc.stderr or proc.stdout or "")[:600]
        logger.warning("archify.quality_failed quality=%s err=%s", q, last_err[:200])

    # Last resort: replace IR with a known-good horizontal chain.
    fb = fallback_architecture_ir(
        title=title or "Architecture",
        language=None,
        top_dirs=[],
    )
    ir_path.write_text(json.dumps(fb, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [
        node,
        str((pkg / "bin" / "archify.mjs").resolve()),
        "deliver",
        "architecture",
        str(ir_path),
        str(out_html),
        "--quality",
        "standard",
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(project_root()),
    )
    if proc.returncode == 0 and out_html.is_file():
        return {
            "status": "done",
            "html_path": str(out_html),
            "ir_path": str(ir_path),
            "quality": "standard",
            "fallback": True,
            "stdout": (proc.stdout or "")[:400],
        }

    raise ArchifyError(f"Archify deliver 失败：{last_err or (proc.stderr or proc.stdout or '')[:600] or 'no output'}")


def fallback_architecture_ir(
    *,
    title: str,
    language: str | None,
    top_dirs: list[str],
) -> dict[str, Any]:
    """Deterministic IR when LLM authoring fails — still renders via Archify."""
    dirs = [
        d
        for d in top_dirs
        if d
        and not str(d).startswith(".")
        and d not in {".git", "node_modules", ".venv", "dist", "build", "vendor", "target"}
    ][:3]
    name = title.split("/")[-1][:28] or "Core"
    components: list[dict[str, Any]] = [
        {
            "id": "users",
            "type": "external",
            "label": "Users",
            "sublabel": "Clients",
            "pos": [40, 220],
            "size": [120, 56],
        },
        {
            "id": "core",
            "type": "backend",
            "label": name,
            "sublabel": (language or "app")[:24],
            "pos": [260, 220],
            "size": [150, 64],
        },
    ]
    # Left→right chain without edge labels (avoids Archify clearance failures).
    connections: list[dict[str, Any]] = [
        {"id": "c0", "from": "users", "to": "core", "variant": "emphasis"},
    ]
    prev = "core"
    for i, d in enumerate(dirs):
        cid = f"mod{i}"
        components.append(
            {
                "id": cid,
                "type": "backend" if i % 2 == 0 else "database",
                "label": d[:24],
                "pos": [480 + i * 200, 220],
                "size": [140, 56],
            }
        )
        connections.append({"id": f"c{i+1}", "from": prev, "to": cid})
        prev = cid
    return {
        "schema_version": 1,
        "diagram_type": "architecture",
        "meta": {
            "title": f"{title} · 架构概览",
            "subtitle": "Bagel fallback diagram",
            "quality_profile": "standard",
            "locale": "zh-CN",
        },
        "components": components,
        "connections": connections,
        "cards": [
            {
                "dot": "cyan",
                "title": "说明",
                "items": [
                    "由 Bagel 根据目录结构生成的兜底架构图",
                    "LLM 可用时会替换为更精确 IR",
                ],
            }
        ],
    }
