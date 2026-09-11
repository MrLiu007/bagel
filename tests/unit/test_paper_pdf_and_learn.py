"""Tests for paper PDF resolution and GitHub learn helpers."""

from __future__ import annotations

from bagel.collectors.papers import extract_arxiv_id, resolve_pdf_url
from bagel.domain.enums import ItemType, SourceType
from bagel.domain.models import IntelItem
from bagel.services.github_learn import (
    _default_pages,
    parse_repo_full_name,
    score_path_for_snippet,
    select_snippet_paths,
)
from bagel.services.prompts import GITHUB_LEARN_PROMPT_VERSION


def test_extract_arxiv_from_hf_papers_url() -> None:
    assert extract_arxiv_id("https://huggingface.co/papers/2608.27906") == "2608.27906"
    assert extract_arxiv_id("hf:2608.27906") == "2608.27906"
    assert extract_arxiv_id("arxiv:2609.05374") == "2609.05374"


def test_resolve_pdf_hf_external_id() -> None:
    url = resolve_pdf_url(
        page_url="https://huggingface.co/papers/2608.27906",
        external_id="hf:2608.27906",
    )
    assert url == "https://arxiv.org/pdf/2608.27906.pdf"


def test_resolve_pdf_stored_url() -> None:
    url = resolve_pdf_url(
        page_url="https://doi.org/10.1/x",
        stored_pdf_url="https://example.com/a.pdf",
    )
    assert url == "https://example.com/a.pdf"


def test_parse_repo_full_name() -> None:
    item = IntelItem(
        item_type=ItemType.GITHUB_REPO,
        source_type=SourceType.GITHUB,
        title="owner/repo",
        url="https://github.com/owner/repo",
        metadata_={"repo_full_name": "owner/repo"},
    )
    assert parse_repo_full_name(item) == "owner/repo"


def test_snippet_path_scoring_prefers_entrypoints() -> None:
    assert score_path_for_snippet("src/main.py") > score_path_for_snippet("tests/foo.py")
    assert score_path_for_snippet("pyproject.toml") > score_path_for_snippet(
        "a/b/c/d/util.py"
    )


def test_select_snippet_paths_covers_top_dirs() -> None:
    tree = [
        "src/app.py",
        "src/util.py",
        "pkg/mod.go",
        "tests/test_x.py",
        "node_modules/x/index.js",
        "README.md",
        "pyproject.toml",
    ]
    picked = select_snippet_paths(tree, top_dirs=["src", "pkg"], max_files=6)
    assert "pyproject.toml" in picked
    assert any(p.startswith("src/") for p in picked)
    assert "node_modules/x/index.js" not in picked


def test_default_pages_include_extension_sections() -> None:
    evidence = {
        "full_name": "acme/demo",
        "url": "https://github.com/acme/demo",
        "description": "demo",
        "language": "Python",
        "stars": 1,
        "topics": ["ai"],
        "top_dirs": ["src", "cli"],
        "languages": {"Python": 100},
        "tree_sample": ["src/main.py", "cli/app.py"],
        "file_snippets": [{"path": "src/main.py", "content": "def main(): ..."}],
    }
    pages = _default_pages(evidence)
    titles = [p["title"] for p in pages]
    assert "扩展指南" in titles
    assert "当前能力与边界" in titles
    assert any(t.startswith("模块 · ") for t in titles)
    module_md = next(p["markdown"] for p in pages if p["title"].startswith("模块 · "))
    assert "现状能力" in module_md
    assert "后续怎么扩展" in module_md
    assert GITHUB_LEARN_PROMPT_VERSION == "github-learn-v3"


def test_paper_has_resolvable_pdf_local_only() -> None:
    from bagel.collectors.papers import paper_has_resolvable_pdf

    assert paper_has_resolvable_pdf(
        page_url="https://arxiv.org/abs/2401.12345",
        stored_pdf_url=None,
    )
    assert paper_has_resolvable_pdf(
        page_url="https://doi.org/10.5281/zenodo.1",
        stored_pdf_url="https://zenodo.org/records/1/files/x.pdf",
    )
    assert not paper_has_resolvable_pdf(
        page_url="https://doi.org/10.5281/zenodo.17036033",
        stored_pdf_url=None,
    )


def test_sanitize_architecture_cards() -> None:
    from bagel.integrations.archify import sanitize_architecture_ir

    cleaned = sanitize_architecture_ir(
        {
            "components": [{"id": "a", "type": "weird", "label": "A"}],
            "cards": [{"title": "x", "body": "hello"}],
        },
        title="demo",
    )
    assert cleaned["components"][0]["type"] == "backend"
    assert cleaned["components"][0]["pos"]
    assert cleaned["cards"][0]["items"] == ["hello"]
    assert "dot" in cleaned["cards"][0]


def test_github_rate_limit_error_message_guides_token() -> None:
    from bagel.services.github_learn import _format_github_http_error

    msg = _format_github_http_error(
        403,
        'API rate limit exceeded for 1.2.3.4. (But here\'s the good news: Authenticated requests get a higher rate limit.)',
        has_token=False,
    )
    assert "GITHUB_TOKEN" in msg
    assert "60" in msg
    auth_msg = _format_github_http_error(403, "API rate limit exceeded", has_token=True)
    assert "认证额度" in auth_msg


def test_meaningful_top_dirs_skip_dotfiles() -> None:
    from bagel.services.github_learn import filter_meaningful_dirs, is_meaningful_top_dir

    assert not is_meaningful_top_dir(".cargo")
    assert not is_meaningful_top_dir(".circleci")
    assert is_meaningful_top_dir("litellm")
    assert filter_meaningful_dirs([".cargo", "src", ".github", "docs"]) == ["src", "docs"]
