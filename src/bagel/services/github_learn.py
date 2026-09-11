"""GitHub project 「学习」— Qoder-style Repo Wiki + Archify architecture diagram."""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType
from bagel.domain.models import IntelItem
from bagel.integrations.archify import (
    ArchifyError,
    deliver_architecture,
    fallback_architecture_ir,
    is_configured as archify_ready,
)
from bagel.integrations.http import build_http_client
from bagel.pipeline.paths import display_path
from bagel.services.llm import LlmClient
from bagel.services.prompts import (
    GITHUB_LEARN_PAGES_SYSTEM,
    GITHUB_LEARN_PAGES_USER_TEMPLATE,
    GITHUB_LEARN_PLAN_SYSTEM,
    GITHUB_LEARN_PROMPT_VERSION,
    GITHUB_LEARN_USER_TEMPLATE,
)
from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.github_learn")

ProgressCallback = Callable[..., None]

_REPO_URL_RE = re.compile(
    r"github\.com[/:](?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+?)(?:\.git)?/?$",
    re.I,
)

_PRIORITY_BASENAMES = frozenset(
    {
        "readme.md",
        "contributing.md",
        "architecture.md",
        "agents.md",
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "makefile",
        "cmakelists.txt",
        "tsconfig.json",
        ".env.example",
        "main.py",
        "app.py",
        "__main__.py",
        "cli.py",
        "index.ts",
        "index.js",
        "main.go",
        "main.rs",
        "mod.rs",
        "lib.rs",
    }
)

_ENTRY_PATH_HINTS = (
    "src/main",
    "src/index",
    "src/app",
    "cmd/",
    "apps/",
    "packages/",
    "internal/",
    "pkg/",
    "lib/",
    "server/",
    "backend/",
    "frontend/",
    "api/",
    "core/",
    "engine/",
    "cli/",
)

_SKIP_TOP_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".gitlab",
        ".circleci",
        ".devcontainer",
        ".vscode",
        ".idea",
        ".cargo",
        ".husky",
        ".yarn",
        ".turbo",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "target",
        "vendor",
        "__pycache__",
        "coverage",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def is_meaningful_top_dir(name: str) -> bool:
    n = (name or "").strip()
    if not n or n.startswith("."):
        return False
    return n.lower() not in _SKIP_TOP_DIRS


def filter_meaningful_dirs(dirs: list[str], *, limit: int = 12) -> list[str]:
    out: list[str] = []
    for d in dirs:
        if is_meaningful_top_dir(d) and d not in out:
            out.append(d)
        if len(out) >= limit:
            break
    return out


def learn_dir(settings: Settings, item_id: uuid.UUID | str) -> Path:
    return Path(settings.data_dir) / "github" / "learn" / str(item_id)


def parse_repo_full_name(item: IntelItem) -> str | None:
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    name = (meta.get("repo_full_name") or "").strip()
    if name and "/" in name:
        return name
    ext = str(meta.get("external_id") or "")
    if ext.startswith("github:repo:"):
        return ext.split(":", 2)[-1]
    m = _REPO_URL_RE.search((item.url or "").strip())
    if m:
        return f"{m.group('owner')}/{m.group('repo').rstrip('/')}"
    title = (item.title or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", title):
        return title
    return None


class GithubApiError(RuntimeError):
    """GitHub API failure with a user-facing Chinese message."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def _gh_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Bagel/0.3 (+https://github.com/MrLiu007/bagel)",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _format_github_http_error(status: int, body: str, *, has_token: bool) -> str:
    low = (body or "").lower()
    if status == 403 and ("rate limit" in low or "api rate limit exceeded" in low):
        if has_token:
            return (
                "GitHub API 已达认证额度上限。请稍后再试，或在 .env 更换/检查 GITHUB_TOKEN。"
            )
        return (
            "GitHub API 匿名额度已用尽（未认证约 60 次/小时）。"
            "请在 .env 配置 GITHUB_TOKEN=ghp_…（经典 PAT，勾选 public_repo 即可），"
            "然后重启 bagel dev。认证后额度约 5000 次/小时。"
        )
    if status in {401, 403} and ("bad credentials" in low or "requires authentication" in low):
        return "GitHub Token 无效或权限不足，请检查 .env 中的 GITHUB_TOKEN。"
    if status == 404:
        return "GitHub 仓库不存在或无权访问（404）。"
    snippet = (body or "").replace("\n", " ")[:160]
    return f"GitHub API {status}：{snippet}"


def _get_json(
    settings: Settings,
    url: str,
    *,
    params: dict | None = None,
    client: Any | None = None,
) -> Any:
    headers = _gh_headers(settings)

    def _once(http: Any) -> Any:
        resp = http.get(url, headers=headers, params=params)
        if resp.status_code >= 400:
            raise GithubApiError(
                _format_github_http_error(
                    resp.status_code,
                    resp.text or "",
                    has_token=bool(settings.github_token),
                ),
                status=resp.status_code,
            )
        return resp.json()

    if client is not None:
        return _once(client)
    with build_http_client(settings, timeout=45.0) as http:
        return _once(http)


def github_rate_limit_remaining(settings: Settings, *, client: Any | None = None) -> dict[str, Any] | None:
    """Best-effort core rate-limit probe. Returns None on failure."""
    try:
        data = _get_json(settings, "https://api.github.com/rate_limit", client=client)
        core = ((data or {}).get("resources") or {}).get("core") or {}
        return {
            "limit": core.get("limit"),
            "remaining": core.get("remaining"),
            "reset": core.get("reset"),
            "authenticated": bool(settings.github_token),
        }
    except Exception:  # noqa: BLE001
        return None


def _fetch_file_text(
    settings: Settings,
    full_name: str,
    path: str,
    *,
    ref: str,
    max_chars: int,
    client: Any | None = None,
) -> str | None:
    """Prefer raw.githubusercontent.com (does not consume REST API quota)."""
    raw_url = f"https://raw.githubusercontent.com/{full_name}/{ref}/{path}"
    try:
        http = client
        close = False
        if http is None:
            http = build_http_client(settings, timeout=30.0)
            close = True
        try:
            resp = http.get(raw_url, headers={"User-Agent": "Bagel/0.3"})
            if resp.status_code == 200 and resp.content:
                text = resp.text
                if len(text) > max_chars:
                    return text[:max_chars] + "\n…(截断)\n"
                return text
        finally:
            if close:
                http.close()
    except Exception as exc:  # noqa: BLE001
        logger.info("github_learn.raw_skip path=%s err=%s", path, exc)

    # Fallback: Contents API (counts against rate limit).
    url = f"https://api.github.com/repos/{full_name}/contents/{path}"
    try:
        data = _get_json(settings, url, params={"ref": ref}, client=client)
    except GithubApiError as exc:
        if exc.status in {403, 429}:
            raise
        logger.info("github_learn.file_skip path=%s err=%s", path, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.info("github_learn.file_skip path=%s err=%s", path, exc)
        return None
    if not isinstance(data, dict) or data.get("type") != "file":
        return None
    size = int(data.get("size") or 0)
    if size > 400_000:
        return None
    content = data.get("content")
    if not content:
        return None
    encoding = (data.get("encoding") or "base64").lower()
    try:
        if encoding == "base64":
            raw = base64.b64decode(content).decode("utf-8", errors="ignore")
        else:
            raw = str(content)
    except Exception:  # noqa: BLE001
        return None
    raw = raw.replace("\r\n", "\n")
    if len(raw) > max_chars:
        return raw[:max_chars] + "\n…(截断)\n"
    return raw


def gather_repo_evidence(
    full_name: str,
    *,
    settings: Settings,
    max_files: int = 80,
) -> dict[str, Any]:
    has_token = bool((settings.github_token or "").strip())
    # Anonymous IP quota is tiny (~60/hr). Keep REST calls minimal without token.
    max_snips = int(getattr(settings, "github_learn_max_snippets", 24) or 24)
    if not has_token:
        max_snips = min(max_snips, 6)

    base = f"https://api.github.com/repos/{full_name}"
    with build_http_client(settings, timeout=45.0) as client:
        rl = github_rate_limit_remaining(settings, client=client)
        if rl is not None:
            remaining = int(rl.get("remaining") or 0)
            if remaining <= 2:
                raise GithubApiError(
                    _format_github_http_error(
                        403,
                        "API rate limit exceeded",
                        has_token=has_token,
                    )
                    + (f"（剩余 {remaining}）" if remaining is not None else ""),
                    status=403,
                )
            if remaining < 8 and not has_token:
                logger.warning(
                    "github_learn.low_quota remaining=%s authenticated=%s",
                    remaining,
                    has_token,
                )

        repo = _get_json(settings, base, client=client)
        default_branch = repo.get("default_branch") or "main"
        languages: dict[str, Any] = {}
        try:
            languages = _get_json(settings, f"{base}/languages", client=client)
        except GithubApiError as exc:
            if exc.status in {403, 429}:
                raise
            logger.info("github_learn.languages_skip err=%s", exc)

        readme = ""
        try:
            rm = _get_json(settings, f"{base}/readme", client=client)
            if isinstance(rm, dict) and rm.get("content"):
                raw = base64.b64decode(rm["content"]).decode("utf-8", errors="ignore")
                readme = raw[:16000]
        except GithubApiError as exc:
            if exc.status in {403, 429}:
                raise
            logger.info("github_learn.readme_skip err=%s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.info("github_learn.readme_skip err=%s", exc)

        tree_sample: list[str] = []
        top_dirs: list[str] = []
        try:
            tree = _get_json(
                settings,
                f"{base}/git/trees/{default_branch}",
                params={"recursive": "1"},
                client=client,
            )
            for t in tree.get("tree") or []:
                if not isinstance(t, dict):
                    continue
                path = t.get("path") or ""
                if "/" not in path and t.get("type") == "tree":
                    top_dirs.append(path)
                if t.get("type") == "blob" and len(tree_sample) < max(max_files * 3, 200):
                    if any(
                        path.endswith(ext)
                        for ext in (
                            ".py",
                            ".ts",
                            ".tsx",
                            ".js",
                            ".go",
                            ".rs",
                            ".java",
                            ".md",
                            ".toml",
                            ".yml",
                            ".yaml",
                            ".json",
                            ".gradle",
                            ".xml",
                        )
                    ):
                        tree_sample.append(path)
            top_dirs = filter_meaningful_dirs(sorted(set(top_dirs)), limit=20)
            tree_sample = tree_sample[: max(max_files * 3, 200)]
        except GithubApiError as exc:
            if exc.status in {403, 429}:
                raise
            logger.info("github_learn.tree_skip err=%s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.info("github_learn.tree_skip err=%s", exc)

        max_chars = int(getattr(settings, "github_learn_snippet_chars", 4000) or 4000)
        max_total = int(getattr(settings, "github_learn_snippet_total_chars", 48000) or 48000)
        paths = select_snippet_paths(
            tree_sample, top_dirs=top_dirs, max_files=max_snips
        )
        snippets: list[dict[str, str]] = []
        total = 0
        for path in paths:
            if total >= max_total:
                break
            text = _fetch_file_text(
                settings,
                full_name,
                path,
                ref=default_branch,
                max_chars=min(max_chars, max_total - total),
                client=client,
            )
            if not text:
                continue
            snippets.append({"path": path, "content": text})
            total += len(text)

    return {
        "full_name": full_name,
        "url": repo.get("html_url") or f"https://github.com/{full_name}",
        "description": repo.get("description") or "",
        "language": repo.get("language") or "",
        "stars": repo.get("stargazers_count"),
        "topics": list(repo.get("topics") or []),
        "default_branch": default_branch,
        "readme": readme,
        "languages": languages if isinstance(languages, dict) else {},
        "top_dirs": top_dirs,
        "tree_sample": tree_sample[:max_files],
        "file_snippets": snippets,
        "auth": "token" if has_token else "anonymous",
    }


def score_path_for_snippet(path: str) -> int:
    """Higher score = more useful for technical wiki evidence."""
    p = path.replace("\\", "/")
    low = p.lower()
    base = low.rsplit("/", 1)[-1]
    score = 0
    if base in _PRIORITY_BASENAMES:
        score += 100
    if any(h in low for h in _ENTRY_PATH_HINTS):
        score += 40
    if low.endswith(
        (".py", ".ts", ".tsx", ".go", ".rs", ".java", ".toml", ".yml", ".yaml", ".md")
    ):
        score += 15
    depth = low.count("/")
    if depth <= 2:
        score += 10
    if depth >= 5:
        score -= 8
    if any(
        seg in low
        for seg in (
            "node_modules/",
            "/vendor/",
            "vendor/",
            "/dist/",
            "/build/",
            ".git/",
            "__pycache__/",
            "/test/",
            "/tests/",
            "__tests__/",
            ".min.",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "cargo.lock",
        )
    ):
        score -= 120
    return score


def select_snippet_paths(
    tree_sample: list[str],
    *,
    top_dirs: list[str] | None = None,
    max_files: int = 24,
) -> list[str]:
    scored = sorted(
        ((score_path_for_snippet(p), p) for p in tree_sample),
        key=lambda x: (-x[0], x[1]),
    )
    picked: list[str] = []
    seen: set[str] = set()
    for sc, path in scored:
        if sc < 20 or path in seen:
            continue
        picked.append(path)
        seen.add(path)
        if len(picked) >= max_files:
            break
    # Ensure at least one file per top dir when possible.
    for d in top_dirs or []:
        if len(picked) >= max_files:
            break
        for sc, path in scored:
            if path.startswith(f"{d}/") and path not in seen and sc >= 20:
                picked.append(path)
                seen.add(path)
                break
    return picked


def _format_snippets(snippets: list[dict[str, str]], *, limit: int = 45000) -> str:
    parts: list[str] = []
    used = 0
    for row in snippets:
        path = row.get("path") or ""
        body = row.get("content") or ""
        chunk = f"### {path}\n```\n{body}\n```\n"
        if used + len(chunk) > limit:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts) if parts else "(无文件片段)"


def _default_core_modules(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for d in filter_meaningful_dirs(list(evidence.get("top_dirs") or []), limit=6):
        paths = [p for p in (evidence.get("tree_sample") or []) if p.startswith(f"{d}/")][
            :5
        ]
        modules.append(
            {
                "name": d,
                "paths": paths or [d],
                "responsibility": f"顶层目录 `{d}`（基于路径推断，细节需对照源码）",
                "tech_highlights": [],
                "extension_hooks": [f"在 `{d}/` 下按现有模式新增模块文件"],
            }
        )
    if not modules:
        modules.append(
            {
                "name": "root",
                "paths": list(evidence.get("tree_sample") or [])[:8],
                "responsibility": "仓库根目录与入口文件",
                "tech_highlights": [],
                "extension_hooks": ["阅读 README 中的扩展/插件说明"],
            }
        )
    return modules


def _default_wiki_plan(
    evidence: dict[str, Any], core_modules: list[dict[str, Any]]
) -> dict[str, Any]:
    docs: list[dict[str, str]] = [
        {
            "title": "项目概览",
            "goal": "定位、目标用户、解决问题与仓库地图",
            "parent": "",
            "hints": "含能力摘要与非目标",
        },
        {
            "title": "系统架构与数据流",
            "goal": "分层、组件交互、关键请求/任务路径",
            "parent": "",
            "hints": "对照 Archify 图",
        },
        {
            "title": "核心模块深入",
            "goal": "模块地图与阅读顺序",
            "parent": "系统架构与数据流",
            "hints": "",
        },
    ]
    for m in core_modules:
        name = str(m.get("name") or "module")
        docs.append(
            {
                "title": f"模块 · {name}",
                "goal": f"深入 {name}：现状能力、实现要点、扩展点",
                "parent": "核心模块深入",
                "hints": "必须含三节：现状能力 / 实现要点 / 后续怎么扩展",
            }
        )
    docs.extend(
        [
            {
                "title": "技术栈与关键实现",
                "goal": "语言/框架/构建与关键代码路径",
                "parent": "",
                "hints": "引用具体文件",
            },
            {
                "title": "当前能力与边界",
                "goal": "已具备能力、明确边界、风险",
                "parent": "",
                "hints": "",
            },
            {
                "title": "扩展指南",
                "goal": "可操作的扩展场景与改动落点",
                "parent": "",
                "hints": "至少两个场景",
            },
            {
                "title": "上手与调试",
                "goal": "安装、运行、常见问题",
                "parent": "",
                "hints": "",
            },
        ]
    )
    return {
        "version": 1,
        "repowiki": {
            "template": "architecture",
            "notes": [
                {
                    "text": "面向技术学习：写清现状能力、实现与扩展点，禁止空泛概述",
                    "author": "bagel",
                }
            ],
            "documents": docs,
        },
    }


def _section_triplet(title: str, body_lines: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        "## 现状能力（现在能做什么）",
        "",
        *(body_lines or ["- 证据不足，请对照仓库 README 与源码。"]),
        "",
        "## 实现要点（关键类型/函数/配置/数据流）",
        "",
        "- 结合下方路径阅读源码；本页为证据不足时的骨架，重新生成可加深。",
        "",
        "## 后续怎么扩展",
        "",
        "- 先定位与目标能力最接近的现有模块，按同目录约定新增。",
        "- 补测试与配置项，避免破坏现有入口。",
        "",
    ]
    return "\n".join(lines)


def _default_pages(
    evidence: dict[str, Any],
    *,
    core_modules: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    name = evidence["full_name"]
    desc = evidence.get("description") or "（无描述）"
    dirs = "、".join(evidence.get("top_dirs") or []) or "（未知）"
    langs = ", ".join(
        f"{k} {v}" for k, v in list((evidence.get("languages") or {}).items())[:8]
    )
    snip_paths = [s.get("path") for s in (evidence.get("file_snippets") or []) if s.get("path")]
    modules = core_modules or _default_core_modules(evidence)
    pages: list[dict[str, str]] = [
        {
            "title": "项目概览",
            "parent": "",
            "markdown": (
                f"# 项目概览\n\n**{name}**\n\n{desc}\n\n"
                f"## 现状能力\n\n- 公开仓库能力以 README 与目录为准（见证据文件）。\n"
                f"- Stars：{evidence.get('stars')}；Topics：{', '.join(evidence.get('topics') or []) or '—'}\n\n"
                f"## 仓库地图\n\n- 主语言：{evidence.get('language') or '—'}\n"
                f"- 顶层目录：{dirs}\n"
                f"- 已拉取片段：{', '.join(f'`{p}`' for p in snip_paths[:12]) or '（无）'}\n"
                f"- 仓库：{evidence.get('url')}\n\n"
                "## 后续怎么扩展\n\n重新生成学习页（force）以在 LLM 可用时写入更深实现分析。\n"
            ),
        },
        {
            "title": "系统架构与数据流",
            "parent": "",
            "markdown": (
                "# 系统架构与数据流\n\n"
                "配合 Archify 架构图阅读。以下为基于目录/语言/片段的初步划分。\n\n"
                f"## 语言占比\n\n{langs or '—'}\n\n"
                f"## 顶层目录\n\n{dirs}\n\n"
                "## 实现要点\n\n"
                + "\n".join(f"- `{p}`" for p in snip_paths[:20])
                + "\n\n## 后续怎么扩展\n\n新增组件时同步更新架构边界与数据流说明。\n"
            ),
        },
        {
            "title": "核心模块深入",
            "parent": "系统架构与数据流",
            "markdown": (
                "# 核心模块深入\n\n阅读顺序建议按子页逐个深入。\n\n"
                + "\n".join(
                    f"- **{m.get('name')}**：{m.get('responsibility')}" for m in modules
                )
                + "\n"
            ),
        },
    ]
    for m in modules:
        mname = str(m.get("name") or "module")
        paths = m.get("paths") or []
        pages.append(
            {
                "title": f"模块 · {mname}",
                "parent": "核心模块深入",
                "markdown": _section_triplet(
                    f"模块 · {mname}",
                    [
                        f"- 职责（推断）：{m.get('responsibility')}",
                        *(f"- 路径：`{p}`" for p in paths[:8]),
                    ],
                ),
            }
        )
    pages.extend(
        [
            {
                "title": "技术栈与关键实现",
                "parent": "",
                "markdown": _section_triplet(
                    "技术栈与关键实现",
                    [
                        f"- 主语言：{evidence.get('language') or '—'}",
                        f"- 语言占比：{langs or '—'}",
                        *(f"- 证据文件：`{p}`" for p in snip_paths[:10]),
                    ],
                ),
            },
            {
                "title": "当前能力与边界",
                "parent": "",
                "markdown": (
                    "# 当前能力与边界\n\n"
                    "## 现状能力\n\n- 以 README 声明为准；本页在 LLM 失败时仅为骨架。\n\n"
                    "## 边界 / 非目标\n\n- 证据不足处勿当作已实现功能。\n\n"
                    "## 后续怎么扩展\n\n- 先补齐自动化测试与配置文档，再扩展对外能力。\n"
                ),
            },
            {
                "title": "扩展指南",
                "parent": "",
                "markdown": (
                    "# 扩展指南\n\n"
                    "## 现状能力\n\n- 仓库当前扩展方式需对照 README / CONTRIBUTING。\n\n"
                    "## 实现要点\n\n"
                    f"- 优先改动落点：{dirs}\n\n"
                    "## 后续怎么扩展\n\n"
                    "### 场景 A：新增同类能力模块\n\n"
                    "1. 找到最接近的现有模块目录\n2. 复制结构并注册到入口/配置\n3. 补测试\n\n"
                    "### 场景 B：接入外部依赖/适配器\n\n"
                    "1. 在 integrations/adapters 类目录新增客户端\n"
                    "2. 用环境变量配置，避免写死密钥\n3. 在学习页重新生成以更新文档\n"
                ),
            },
            {
                "title": "上手与调试",
                "parent": "",
                "markdown": (
                    f"# 上手与调试\n\n```bash\ngit clone {evidence.get('url')}.git\n"
                    f"cd {name.split('/')[-1]}\n```\n\n"
                    "请阅读仓库 README 安装与运行说明。\n\n"
                    "## 调试建议\n\n- 先跑官方 quickstart / tests\n- 对照已拉取源码片段中的入口文件\n"
                ),
            },
        ]
    )
    return pages

def _write_wiki(
    out: Path,
    *,
    wiki_plan: dict[str, Any],
    pages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    zh = out / ".qoder" / "repowiki" / "zh"
    zh.mkdir(parents=True, exist_ok=True)
    plan_dir = out / ".qoder" / "repowiki"
    (plan_dir / "wiki_plan.json").write_text(
        json.dumps(wiki_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (plan_dir / "wiki_plan.yaml").write_text(_wiki_plan_yaml(wiki_plan), encoding="utf-8")
    index: list[dict[str, str]] = []
    for i, page in enumerate(pages):
        title = str(page.get("title") or f"page-{i}")
        slug = re.sub(r"[^\w\-]+", "-", title, flags=re.U).strip("-").lower() or f"p{i}"
        fname = str(page.get("file") or f"{i:02d}-{slug}.md")
        status = str(page.get("status") or "ready")
        body = str(page.get("markdown") or "")
        if not body:
            body = (
                f"# {title}\n\n"
                "> 本页尚未生成。打开本页时将按需深度撰写并持久化。\n"
            )
            status = "pending"
        (zh / fname).write_text(body, encoding="utf-8")
        index.append(
            {
                "title": title,
                "parent": str(page.get("parent") or ""),
                "file": fname,
                "rel": f".qoder/repowiki/zh/{fname}",
                "status": status,
                "goal": str(page.get("goal") or ""),
                "hints": str(page.get("hints") or ""),
            }
        )
    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index


def _wiki_plan_yaml(plan: dict[str, Any]) -> str:
    lines = ["version: 1", "repowiki:", "  template: architecture", "  documents:"]
    docs = ((plan.get("repowiki") or {}).get("documents") or []) if isinstance(plan, dict) else []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title") or "").replace('"', "'")
        goal = str(doc.get("goal") or title).replace('"', "'")
        parent = str(doc.get("parent") or "").replace('"', "'")
        lines.append(f'    - title: "{title}"')
        lines.append(f'      goal: "{goal}"')
        if parent:
            lines.append(f'      parent: "{parent}"')
    lines.append("")
    return "\n".join(lines)


def _evidence_user_block(evidence: dict[str, Any]) -> dict[str, str]:
    langs_txt = "\n".join(
        f"- {k}: {v}" for k, v in list((evidence.get("languages") or {}).items())[:12]
    )
    return {
        "full_name": evidence["full_name"],
        "url": evidence["url"],
        "default_branch": evidence["default_branch"],
        "language": evidence.get("language") or "",
        "stars": str(evidence.get("stars")),
        "topics": ", ".join(evidence.get("topics") or []),
        "description": evidence.get("description") or "",
        "readme": (evidence.get("readme") or "")[:10000],
        "languages": langs_txt or "(无)",
        "top_dirs": ", ".join(evidence.get("top_dirs") or []) or "(无)",
        "tree_sample": "\n".join(evidence.get("tree_sample") or [])[:5000] or "(无)",
        "file_snippets": _format_snippets(list(evidence.get("file_snippets") or [])),
    }


def _merge_pages(
    specs: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_title = {
        str(p.get("title")): p
        for p in generated
        if isinstance(p, dict) and p.get("title") and p.get("markdown")
    }
    fb = {
        str(p.get("title")): p
        for p in fallback
        if isinstance(p, dict) and p.get("title")
    }
    out: list[dict[str, Any]] = []
    for spec in specs:
        title = str(spec.get("title") or "")
        if not title:
            continue
        page = by_title.get(title) or fb.get(title)
        if page:
            out.append(
                {
                    "title": title,
                    "parent": str(spec.get("parent") or page.get("parent") or ""),
                    "markdown": str(page.get("markdown") or f"# {title}\n"),
                }
            )
        else:
            out.append(
                {
                    "title": title,
                    "parent": str(spec.get("parent") or ""),
                    "markdown": f"# {title}\n\n证据不足，未能生成正文。\n",
                }
            )
    return out


def _plan_wiki_with_llm(
    evidence: dict[str, Any],
    *,
    settings: Settings,
    on_progress: ProgressCallback | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str | None]:
    """Plan TOC + architecture IR only (no full page bodies)."""
    llm = LlmClient(settings)
    core_modules = _default_core_modules(evidence)
    wiki_plan = _default_wiki_plan(evidence, core_modules)
    arch_ir = fallback_architecture_ir(
        title=evidence["full_name"],
        language=evidence.get("language"),
        top_dirs=list(evidence.get("top_dirs") or []),
    )
    errors: list[str] = []
    block = _evidence_user_block(evidence)
    if on_progress:
        on_progress(current=4, total=10, message="LLM 规划 Wiki 目录…", percent=40.0)
    parsed_plan, err1 = llm.complete_json(
        system=GITHUB_LEARN_PLAN_SYSTEM,
        user=GITHUB_LEARN_USER_TEMPLATE.format(**block),
    )
    if err1:
        errors.append(f"plan:{err1}")
    if parsed_plan:
        if isinstance(parsed_plan.get("wiki_plan"), dict):
            wiki_plan = parsed_plan["wiki_plan"]
        if isinstance(parsed_plan.get("core_modules"), list) and parsed_plan["core_modules"]:
            core_modules = [
                m
                for m in parsed_plan["core_modules"]
                if isinstance(m, dict)
                and m.get("name")
                and is_meaningful_top_dir(str(m.get("name")))
            ] or core_modules
            docs = list(((wiki_plan.get("repowiki") or {}).get("documents")) or [])
            titles = {str(d.get("title")) for d in docs if isinstance(d, dict)}
            if "核心模块深入" not in titles:
                docs.append(
                    {
                        "title": "核心模块深入",
                        "goal": "模块地图",
                        "parent": "系统架构与数据流",
                    }
                )
            for m in core_modules:
                t = f"模块 · {m['name']}"
                if t not in titles:
                    docs.append(
                        {
                            "title": t,
                            "goal": f"深入 {m['name']}",
                            "parent": "核心模块深入",
                            "hints": "现状能力 / 实现要点 / 后续怎么扩展",
                        }
                    )
            wiki_plan.setdefault("repowiki", {})["documents"] = docs
        if isinstance(parsed_plan.get("architecture"), dict):
            arch_ir = parsed_plan["architecture"]
            arch_ir.setdefault("schema_version", 1)
            arch_ir.setdefault("diagram_type", "architecture")
            arch_ir.setdefault("meta", {"title": evidence["full_name"]})
    docs = list(((wiki_plan.get("repowiki") or {}).get("documents")) or [])
    if not docs:
        wiki_plan = _default_wiki_plan(evidence, core_modules)
    return wiki_plan, arch_ir, core_modules, ("; ".join(errors) if errors else None)


def _stub_pages_from_plan(
    wiki_plan: dict[str, Any],
    *,
    overview_markdown: str | None = None,
) -> list[dict[str, Any]]:
    docs = list(((wiki_plan.get("repowiki") or {}).get("documents")) or [])
    pages: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title") or f"page-{i}")
        slug = re.sub(r"[^\w\-]+", "-", title, flags=re.U).strip("-").lower() or f"p{i}"
        fname = f"{i:02d}-{slug}.md"
        is_overview = title == "项目概览" or i == 0
        if is_overview and overview_markdown:
            pages.append(
                {
                    "title": title,
                    "parent": str(doc.get("parent") or ""),
                    "file": fname,
                    "status": "ready",
                    "goal": str(doc.get("goal") or ""),
                    "hints": str(doc.get("hints") or ""),
                    "markdown": overview_markdown,
                }
            )
        else:
            pages.append(
                {
                    "title": title,
                    "parent": str(doc.get("parent") or ""),
                    "file": fname,
                    "status": "pending",
                    "goal": str(doc.get("goal") or ""),
                    "hints": str(doc.get("hints") or ""),
                    "markdown": "",
                }
            )
    return pages


def _load_saved_evidence(out: Path) -> dict[str, Any] | None:
    ev = out / "evidence.json"
    sn = out / "snippets.json"
    if not ev.is_file():
        return None
    data = json.loads(ev.read_text(encoding="utf-8"))
    if sn.is_file():
        data["file_snippets"] = json.loads(sn.read_text(encoding="utf-8"))
    return data


def _save_evidence(out: Path, evidence: dict[str, Any], core_modules: list[dict[str, Any]]) -> None:
    snippets = list(evidence.get("file_snippets") or [])
    (out / "snippets.json").write_text(
        json.dumps(snippets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = {
        k: v for k, v in evidence.items() if k not in {"readme", "file_snippets"}
    } | {
        "readme": (evidence.get("readme") or "")[:16000],
        "snippet_paths": [s.get("path") for s in snippets],
        "core_modules": core_modules,
    }
    (out / "evidence.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _generate_one_page(
    evidence: dict[str, Any],
    *,
    settings: Settings,
    page_spec: dict[str, Any],
    core_modules: list[dict[str, Any]],
) -> tuple[str, str | None]:
    llm = LlmClient(settings)
    block = _evidence_user_block(evidence)
    user = GITHUB_LEARN_PAGES_USER_TEMPLATE.format(
        full_name=evidence["full_name"],
        description=evidence.get("description") or "",
        language=evidence.get("language") or "",
        page_specs=json.dumps([page_spec], ensure_ascii=False, indent=2),
        core_modules=json.dumps(core_modules, ensure_ascii=False, indent=2)[:6000],
        file_snippets=block["file_snippets"][:28000],
        readme=block["readme"][:6000],
    )
    parsed, err = llm.complete_json(system=GITHUB_LEARN_PAGES_SYSTEM, user=user)
    title = str(page_spec.get("title") or "")
    if parsed and isinstance(parsed.get("pages"), list):
        for p in parsed["pages"]:
            if isinstance(p, dict) and p.get("title") == title and p.get("markdown"):
                return str(p["markdown"]), err
        for p in parsed["pages"]:
            if isinstance(p, dict) and p.get("markdown"):
                return str(p["markdown"]), err
    fb = _default_pages(evidence, core_modules=core_modules)
    for p in fb:
        if p.get("title") == title:
            return str(p.get("markdown") or f"# {title}\n"), err
    return f"# {title}\n\n证据不足，未能生成正文。\n", err or "llm_empty"


def run_github_learn(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    on_progress: ProgressCallback | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bootstrap: evidence + TOC + overview page + Archify. Detail pages are lazy."""
    settings = settings or get_settings()
    if not settings.enable_github_learn:
        return {"status": "FAILED", "error": "未启用 GitHub 学习：ENABLE_GITHUB_LEARN=true"}

    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "无效条目 ID"}

    item = session.get(IntelItem, iid)
    if not item or item.item_type not in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
        return {"status": "FAILED", "error": "条目不存在或不是 GitHub 项目"}

    out = learn_dir(settings, item.id)
    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    learn_meta = meta.get("learn") if isinstance(meta.get("learn"), dict) else {}
    if (
        not force
        and learn_meta.get("status") in {"done", "indexed"}
        and (out / "index.json").is_file()
        and learn_meta.get("prompt_version") == GITHUB_LEARN_PROMPT_VERSION
    ):
        return {
            "status": "SUCCESS",
            "skipped": True,
            "learn": learn_meta,
            "detail_url": f"/github/learn/{item.id}",
        }

    full_name = parse_repo_full_name(item)
    if not full_name:
        return {"status": "FAILED", "error": "无法解析 owner/repo"}

    if on_progress:
        on_progress(current=1, total=10, message=f"采集仓库证据 {full_name}…", percent=10.0)

    evidence = None
    try:
        evidence = gather_repo_evidence(
            full_name,
            settings=settings,
            max_files=settings.github_learn_max_files,
        )
    except GithubApiError as exc:
        cached = _load_saved_evidence(out)
        if cached and cached.get("full_name"):
            evidence = cached
            if on_progress:
                on_progress(
                    current=2,
                    total=10,
                    message="GitHub 额度不足，改用本地证据缓存…",
                    percent=18.0,
                )
            logger.warning("github_learn.use_cache_after_api_error err=%s", exc.message)
        else:
            return {"status": "FAILED", "error": exc.message}
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAILED", "error": f"GitHub API 失败：{exc}"}

    if evidence is None:
        return {"status": "FAILED", "error": "未能采集仓库证据"}

    if on_progress:
        n = len(evidence.get("file_snippets") or [])
        on_progress(current=3, total=10, message=f"已拉取 {n} 个源码片段…", percent=28.0)

    wiki_plan, arch_ir, core_modules, llm_err = _plan_wiki_with_llm(
        evidence, settings=settings, on_progress=on_progress
    )

    overview_spec = None
    docs = list(((wiki_plan.get("repowiki") or {}).get("documents")) or [])
    for d in docs:
        if isinstance(d, dict) and (d.get("title") == "项目概览" or not overview_spec):
            overview_spec = d
            if d.get("title") == "项目概览":
                break
    overview_md = None
    if overview_spec:
        if on_progress:
            on_progress(current=6, total=10, message="撰写首页「项目概览」…", percent=55.0)
        overview_md, page_err = _generate_one_page(
            evidence,
            settings=settings,
            page_spec=overview_spec,
            core_modules=core_modules,
        )
        if page_err:
            llm_err = f"{llm_err}; overview:{page_err}" if llm_err else f"overview:{page_err}"

    pages = _stub_pages_from_plan(wiki_plan, overview_markdown=overview_md)

    if on_progress:
        on_progress(current=8, total=10, message="写入 Wiki 目录（详情页懒加载）…", percent=75.0)

    out.mkdir(parents=True, exist_ok=True)
    _save_evidence(out, evidence, core_modules)
    index = _write_wiki(out, wiki_plan=wiki_plan, pages=pages)

    diagram_rel = None
    diagram_error = None
    html_path = out / "architecture.html"
    if on_progress:
        on_progress(current=9, total=10, message="Archify 渲染架构图…", percent=88.0)
    try:
        if not archify_ready(settings):
            from bagel.services.archify_setup import ensure_archify_on_startup

            ensure_archify_on_startup(settings=settings)
        deliver_architecture(arch_ir, out_html=html_path, settings=settings)
        diagram_rel = display_path(str(html_path))
    except ArchifyError as exc:
        diagram_error = exc.message
        logger.warning("github_learn.archify_failed err=%s", exc.message)
        (out / "architecture.architecture.json").write_text(
            json.dumps(arch_ir, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        diagram_error = str(exc)[:300]
        logger.warning("github_learn.archify_exception err=%s", exc)

    ready_n = sum(1 for p in index if p.get("status") == "ready")
    learn_meta = {
        "status": "indexed",
        "mode": "lazy",
        "full_name": full_name,
        "prompt_version": GITHUB_LEARN_PROMPT_VERSION,
        "pages": len(index),
        "pages_ready": ready_n,
        "snippets": len(evidence.get("file_snippets") or []),
        "path": display_path(str(out)),
        "diagram": diagram_rel,
        "diagram_error": diagram_error,
        "llm_error": llm_err,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    meta["learn"] = learn_meta
    item.metadata_ = meta
    session.flush()

    if on_progress:
        on_progress(current=10, total=10, message="目录已就绪，详情页按需生成", percent=100.0)

    return {
        "status": "SUCCESS",
        "learn": learn_meta,
        "detail_url": f"/github/learn/{item.id}",
        "index": index,
    }


def run_github_learn_page(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    page_file: str,
    on_progress: ProgressCallback | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Lazy-generate one wiki page and persist to disk."""
    settings = settings or get_settings()
    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "无效条目 ID"}

    item = session.get(IntelItem, iid)
    if not item:
        return {"status": "FAILED", "error": "条目不存在"}

    out = learn_dir(settings, item.id)
    index_path = out / "index.json"
    if not index_path.is_file():
        return {"status": "FAILED", "error": "请先点击「开始分析」生成 Wiki 目录"}

    index = json.loads(index_path.read_text(encoding="utf-8"))
    target = next((p for p in index if p.get("file") == page_file), None)
    if not target:
        return {"status": "FAILED", "error": f"未知页面：{page_file}"}

    zh = out / ".qoder" / "repowiki" / "zh"
    md_path = zh / page_file
    if (
        not force
        and target.get("status") == "ready"
        and md_path.is_file()
        and "尚未生成" not in md_path.read_text(encoding="utf-8")[:80]
    ):
        return {
            "status": "SUCCESS",
            "skipped": True,
            "page": target,
            "detail_url": f"/github/learn/{item.id}?page={page_file}",
        }

    evidence = _load_saved_evidence(out)
    if not evidence or not evidence.get("full_name"):
        return {"status": "FAILED", "error": "缺少证据缓存，请重新「开始分析」"}

    core_modules = list(evidence.get("core_modules") or [])
    if on_progress:
        on_progress(
            current=2,
            total=5,
            message=f"撰写「{target.get('title')}」…",
            percent=40.0,
        )

    page_spec = {
        "title": target.get("title"),
        "parent": target.get("parent") or "",
        "goal": target.get("goal") or target.get("title"),
        "hints": target.get("hints") or "现状能力 / 实现要点 / 后续怎么扩展",
    }
    markdown, err = _generate_one_page(
        evidence, settings=settings, page_spec=page_spec, core_modules=core_modules
    )
    zh.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    target["status"] = "ready"
    for row in index:
        if row.get("file") == page_file:
            row["status"] = "ready"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    learn_meta = dict(meta.get("learn") if isinstance(meta.get("learn"), dict) else {})
    learn_meta["pages_ready"] = sum(1 for p in index if p.get("status") == "ready")
    learn_meta["updated_at"] = datetime.now(UTC).isoformat()
    if err:
        learn_meta["last_page_error"] = err
    if learn_meta.get("pages_ready") == len(index):
        learn_meta["status"] = "done"
    else:
        learn_meta["status"] = "indexed"
    meta["learn"] = learn_meta
    item.metadata_ = meta
    session.flush()

    if on_progress:
        on_progress(current=5, total=5, message="页面已生成", percent=100.0)

    return {
        "status": "SUCCESS",
        "page": target,
        "llm_error": err,
        "detail_url": f"/github/learn/{item.id}?page={page_file}",
    }


def load_learn_bundle(settings: Settings, item_id: uuid.UUID | str) -> dict[str, Any] | None:
    out = learn_dir(settings, item_id)
    index_path = out / "index.json"
    if not index_path.is_file():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    pages = []
    for row in index:
        fp = out / ".qoder" / "repowiki" / "zh" / row["file"]
        md = fp.read_text(encoding="utf-8") if fp.is_file() else ""
        status = row.get("status") or (
            "ready" if md and "尚未生成" not in md[:80] else "pending"
        )
        pages.append({**row, "status": status, "markdown": md})
    plan = None
    plan_json = out / ".qoder" / "repowiki" / "wiki_plan.json"
    if plan_json.is_file():
        plan = json.loads(plan_json.read_text(encoding="utf-8"))
    return {
        "root": display_path(str(out)),
        "pages": pages,
        "wiki_plan": plan,
        "diagram_exists": (out / "architecture.html").is_file(),
    }
