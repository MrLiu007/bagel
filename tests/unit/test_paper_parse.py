"""Unit tests for paper PDF URL resolution and parse load-balancing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bagel.collectors.papers import extract_arxiv_id, resolve_pdf_url
from bagel.services import paper_parse
from bagel.settings import Settings


def test_extract_arxiv_id_from_abs() -> None:
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345") == "2401.12345"
    assert extract_arxiv_id("https://arxiv.org/pdf/2401.12345v2.pdf") == "2401.12345"
    assert extract_arxiv_id("arxiv:2401.12345v1") == "2401.12345"


def test_resolve_pdf_url_arxiv() -> None:
    url = resolve_pdf_url(page_url="https://arxiv.org/abs/2401.12345", external_id="arxiv:2401.12345")
    assert url == "https://arxiv.org/pdf/2401.12345.pdf"


def test_resolve_pdf_url_openalex_oa() -> None:
    url = resolve_pdf_url(
        page_url="https://doi.org/10.1/x",
        raw={"open_access": {"oa_url": "https://example.com/paper.pdf"}},
    )
    assert url == "https://example.com/paper.pdf"


def test_pick_providers_round_robin(monkeypatch) -> None:
    s = Settings(
        enable_paper_parse=True,
        paper_parse_providers="mineru,kimi",
        paper_parse_strategy="round_robin",
        enable_mineru=True,
        mineru_api_token="tok",
        enable_kimi_files=True,
        kimi_api_key="kkey",
    )
    with patch.object(paper_parse, "_rr_index", 0):
        a = paper_parse._pick_providers(s)
        b = paper_parse._pick_providers(s)
    assert set(a) == {"mineru", "kimi"}
    assert set(b) == {"mineru", "kimi"}
    assert a[0] != b[0]


def test_parse_local_pdf_failover(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    s = Settings(
        enable_paper_parse=True,
        paper_parse_providers="mineru,kimi",
        paper_parse_strategy="failover",
        enable_mineru=True,
        mineru_api_token="tok",
        enable_kimi_files=True,
        kimi_api_key="kkey",
    )

    def boom(*_a, **_k):
        raise RuntimeError("mineru down")

    def ok(*_a, **_k):
        return {"provider": "kimi", "status": "done", "markdown": "# hi", "chars": 4}

    with (
        patch("bagel.services.paper_parse.mineru.parse_pdf_file", side_effect=boom),
        patch("bagel.services.paper_parse.kimi_files.parse_pdf_file", side_effect=ok),
    ):
        result = paper_parse.parse_local_pdf(pdf, settings=s)
    assert result["status"] == "done"
    assert result["provider"] == "kimi"
    assert result["tried"] == ["mineru", "kimi"]
