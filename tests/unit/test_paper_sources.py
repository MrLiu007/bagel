"""Tests for paper source family aggregation and landing URL preference."""

from __future__ import annotations

from bagel.collectors.papers import expand_doi_landing, prefer_paper_landing_url
from bagel.pipeline.paper_sources import family_for_source


def test_arxiv_categories_aggregate() -> None:
    a = family_for_source(name="arXiv cs.AI", url="arxiv:cs.AI")
    b = family_for_source(name="arXiv cs.LG", url="arxiv:cs.LG")
    assert a.key == b.key == "arxiv"
    assert a.label == "arXiv"


def test_openalex_and_hf_families() -> None:
    assert family_for_source(name="OpenAlex AI", url="openalex:C1").key == "openalex"
    assert family_for_source(name="Hugging Face Papers", url="hf:daily").key == "hf"


def test_expand_zenodo_doi_to_direct() -> None:
    assert expand_doi_landing("https://doi.org/10.5281/zenodo.17036033") == (
        "https://zenodo.org/records/17036033"
    )
    assert expand_doi_landing("10.5281/zenodo.1") == "https://zenodo.org/records/1"


def test_prefer_arxiv_over_doi() -> None:
    url = prefer_paper_landing_url(
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.5281/zenodo.17036033",
            "ids": {"arxiv": "https://arxiv.org/abs/2401.12345", "doi": "https://doi.org/10.5281/zenodo.17036033"},
        }
    )
    assert url == "https://arxiv.org/abs/2401.12345"


def test_prefer_zenodo_direct_when_no_arxiv() -> None:
    url = prefer_paper_landing_url(
        {
            "id": "https://openalex.org/W2",
            "doi": "https://doi.org/10.5281/zenodo.17036033",
            "ids": {"doi": "https://doi.org/10.5281/zenodo.17036033"},
        }
    )
    assert url == "https://zenodo.org/records/17036033"


def test_prefer_publisher_landing_over_doi() -> None:
    url = prefer_paper_landing_url(
        {
            "id": "https://openalex.org/W3",
            "doi": "https://doi.org/10.1234/x",
            "primary_location": {"landing_page_url": "https://publisher.example/paper/x"},
        }
    )
    assert url == "https://publisher.example/paper/x"


def test_prefer_skips_data_deposit_when_publisher_exists() -> None:
    url = prefer_paper_landing_url(
        {
            "id": "https://openalex.org/W4",
            "doi": "https://doi.org/10.5282/ubm/data.716",
            "best_oa_location": {"landing_page_url": "https://data.ub.uni-muenchen.de/716/"},
            "primary_location": {
                "landing_page_url": "https://www.cambridge.org/core/journals/phonology/article/x"
            },
        }
    )
    assert "cambridge.org" in url
    assert "data.ub." not in url


def test_data_deposit_hint_when_no_pdf(monkeypatch) -> None:
    from bagel.collectors import papers as papers_mod

    monkeypatch.setattr(papers_mod, "_pdf_from_landing_page", lambda *_a, **_k: None)
    monkeypatch.setattr(papers_mod, "_unpaywall_pdf", lambda *_a, **_k: None)
    pdf, hint = papers_mod.resolve_pdf_url_with_fallback(
        page_url="https://data.ub.uni-muenchen.de/716/",
        fetch_remote=True,
    )
    assert pdf is None
    assert hint and ("数据仓储" in hint or "补充材料" in hint)
