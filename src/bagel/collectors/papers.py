"""Paper collectors — arXiv / OpenAlex / Hugging Face Papers / Semantic Scholar."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from bagel.settings import get_settings

USER_AGENT = "AI-bagel/0.2 (paper-collector; research)"


@dataclass
class PaperRecord:
    title: str
    url: str
    summary: str
    authors: str
    published_at: datetime | None
    source_name: str
    external_id: str
    venue: str = ""
    raw: dict[str, Any] | None = None


def _client(timeout: float = 40.0) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=timeout,
        proxy=settings.proxy_url or None,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def fetch_arxiv(category: str, *, max_results: int = 25) -> list[PaperRecord]:
    cat = category.strip()
    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query=cat:{quote_plus(cat)}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    with _client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        payload = resp.text
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(payload)
    out: list[PaperRecord] = []
    for entry in root.findall("a:entry", ns):
        title = re.sub(r"\s+", " ", (entry.findtext("a:title", default="", namespaces=ns) or "").strip())
        link = ""
        for lk in entry.findall("a:link", ns):
            if lk.attrib.get("type") == "text/html" or lk.attrib.get("rel") == "alternate":
                link = lk.attrib.get("href") or link
        if not link:
            link = entry.findtext("a:id", default="", namespaces=ns) or ""
        summary = re.sub(
            r"\s+", " ", (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        )
        authors = ", ".join(
            (a.findtext("a:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("a:author", ns)
        )
        published = _parse_date(entry.findtext("a:published", default=None, namespaces=ns))
        arxiv_id = (entry.findtext("a:id", default="", namespaces=ns) or link).rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.I)
        if not title or not link:
            continue
        # Prefer versionless abs URL for cross-source dedupe with HF papers.
        if arxiv_id:
            link = f"https://arxiv.org/abs/{arxiv_id}"
        out.append(
            PaperRecord(
                title=title,
                url=link,
                summary=summary[:2000],
                authors=authors[:255],
                published_at=published,
                source_name=f"arXiv {cat}",
                external_id=f"arxiv:{arxiv_id}",
                venue="arXiv",
            )
        )
    return out


def fetch_openalex(*, concept_id: str = "C154945302", max_results: int = 25) -> list[PaperRecord]:
    url = (
        "https://api.openalex.org/works"
        f"?filter=concepts.id:{concept_id}"
        "&sort=publication_date:desc"
        f"&per_page={max_results}"
    )
    with _client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[PaperRecord] = []
    for row in data.get("results") or []:
        title = (row.get("display_name") or "").strip()
        link = row.get("doi")
        if link and not str(link).startswith("http"):
            link = f"https://doi.org/{link}"
        if not link:
            link = row.get("id") or ""
        abstract = row.get("abstract") or ""
        if not abstract and isinstance(row.get("abstract_inverted_index"), dict):
            inv = row["abstract_inverted_index"]
            positions: list[tuple[int, str]] = []
            for word, idxs in inv.items():
                for idx in idxs:
                    positions.append((idx, word))
            abstract = " ".join(w for _, w in sorted(positions))
        authors = ", ".join(
            (a.get("author") or {}).get("display_name") or ""
            for a in (row.get("authorships") or [])[:8]
        )
        pub = None
        if row.get("publication_date"):
            try:
                pub = datetime.fromisoformat(str(row["publication_date"])).replace(tzinfo=UTC)
            except ValueError:
                pub = None
        if not title or not link:
            continue
            oa_id = str(row.get("id") or "").rstrip("/")
            oa_key = oa_id.rsplit("/", 1)[-1] if oa_id else title[:48]
            out.append(
                PaperRecord(
                    title=title,
                    url=str(link),
                    summary=str(abstract)[:2000],
                    authors=authors[:255],
                    published_at=pub,
                    source_name="OpenAlex",
                    external_id=f"openalex:{oa_key}",
                    venue="OpenAlex",
                    raw=row,
                )
            )
    return out


def fetch_hf_papers(*, max_results: int = 25) -> list[PaperRecord]:
    url = "https://huggingface.co/api/daily_papers"
    with _client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[PaperRecord] = []
    if not isinstance(data, list):
        return out
    for row in data[:max_results]:
        paper = row.get("paper") or row
        title = (paper.get("title") or "").strip()
        arxiv_id = paper.get("id") or paper.get("arxiv_id") or ""
        arxiv_id = re.sub(r"v\d+$", "", str(arxiv_id), flags=re.I)
        link = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else (paper.get("url") or "")
        summary = (paper.get("summary") or paper.get("abstract") or "").strip()
        authors = ", ".join(
            (a.get("name") if isinstance(a, dict) else str(a))
            for a in (paper.get("authors") or [])[:8]
        )
        pub = _parse_date(paper.get("publishedAt") or paper.get("published"))
        if not title:
            continue
        if not link:
            link = f"hf://{title[:40]}"
        out.append(
            PaperRecord(
                title=title,
                url=link,
                summary=summary[:2000],
                authors=authors[:255],
                published_at=pub,
                source_name="Hugging Face Papers",
                external_id=f"hf:{arxiv_id or title[:48]}",
                venue="Hugging Face",
                raw=paper if isinstance(paper, dict) else None,
            )
        )
    return out


def fetch_semantic_scholar(query: str, *, max_results: int = 20) -> list[PaperRecord]:
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={quote_plus(query)}&limit={max_results}"
        "&fields=title,url,abstract,authors,year,externalIds,publicationDate"
    )
    with _client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[PaperRecord] = []
    for row in data.get("data") or []:
        title = (row.get("title") or "").strip()
        link = row.get("url") or ""
        ext = row.get("externalIds") or {}
        if not link and ext.get("ArXiv"):
            link = f"https://arxiv.org/abs/{ext['ArXiv']}"
        if not link and ext.get("DOI"):
            link = f"https://doi.org/{ext['DOI']}"
        authors = ", ".join(a.get("name") or "" for a in (row.get("authors") or [])[:8])
        pub = _parse_date(row.get("publicationDate"))
        if not title:
            continue
        if not link:
            link = f"https://www.semanticscholar.org/paper/{row.get('paperId')}"
        out.append(
            PaperRecord(
                title=title,
                url=link,
                summary=(row.get("abstract") or "")[:2000],
                authors=authors[:255],
                published_at=pub,
                source_name="Semantic Scholar",
                external_id=f"s2:{row.get('paperId') or title[:48]}",
                venue="Semantic Scholar",
                raw=row,
            )
        )
    return out


def fetch_from_source(name: str, url: str) -> list[PaperRecord]:
    """Dispatch by URL / name convention used in seed & settings."""
    lower = (url or "").lower().strip()
    label = (name or "").lower()
    if lower.startswith("arxiv:"):
        return fetch_arxiv(url.split(":", 1)[1])
    if "export.arxiv.org" in lower:
        m = re.search(r"cat:([A-Za-z0-9.]+)", url)
        return fetch_arxiv(m.group(1) if m else "cs.AI")
    if lower.startswith("openalex:") or "openalex.org" in lower:
        m = re.search(r"(C\d+)", url, flags=re.I)
        return fetch_openalex(concept_id=m.group(1) if m else "C154945302")
    if lower.startswith("hf:") or "huggingface.co" in lower or "hf papers" in label:
        return fetch_hf_papers()
    if lower.startswith("s2:") or "semanticscholar.org" in lower:
        if lower.startswith("s2:"):
            q = url.split(":", 1)[1]
        else:
            m = re.search(r"query=([^&]+)", url)
            q = m.group(1) if m else "large language model"
        return fetch_semantic_scholar(q)
    if re.fullmatch(r"cs\.[A-Za-z]+", url.strip()):
        return fetch_arxiv(url.strip())
    return []
