"""Paper collectors — arXiv / OpenAlex / Hugging Face Papers / Semantic Scholar."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from bagel.settings import get_settings

USER_AGENT = "Bagel/0.3 (paper-collector; +https://github.com/MrLiu007/bagel)"


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


def _client(timeout: float = 25.0) -> httpx.Client:
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


def expand_doi_landing(doi_or_url: str | None) -> str | None:
    """Turn DOI into a browser-friendly landing URL.

    Prefer known publisher hosts over doi.org (often blocked / slow in CN).
    """
    if not doi_or_url:
        return None
    text = str(doi_or_url).strip()
    doi = None
    # Local import cycle-safe: extract_doi defined below — call after definition via late use
    m = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.I)
    if m:
        doi = m.group(0).rstrip(".,;)")
    elif text.lower().startswith("doi:"):
        doi = text.split(":", 1)[1].strip()
    if not doi:
        return None
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    zm = re.match(r"10\.5281/zenodo\.(\d+)", doi, flags=re.I)
    if zm:
        return f"https://zenodo.org/records/{zm.group(1)}"
    return f"https://doi.org/{doi}"


def _is_data_deposit_url(url: str | None) -> bool:
    u = (url or "").lower()
    return any(
        x in u
        for x in (
            "data.ub.",
            "figshare.com",
            "dryad.org",
            "osf.io/",
            "dataverse",
            "zenodo.org/records",
            "open.data",
            "/dataset",
            "supplementary data",
        )
    )


def prefer_paper_landing_url(row: dict[str, Any]) -> str:
    """Pick a human-openable landing URL from OpenAlex (or similar) work JSON.

    Priority: arXiv abs → publisher/OA landing (non-doi.org, non-data-deposit) →
    Zenodo direct → doi.org → OpenAlex work page. Using raw DOI or data-repo
    landings as item.url was a common cause of「页面无法打开 / 无 PDF」.
    """
    ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
    arxiv = str(ids.get("arxiv") or "").strip()
    if arxiv:
        aid = arxiv.rstrip("/").rsplit("/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid, flags=re.I)
        if aid:
            return f"https://arxiv.org/abs/{aid}"

    candidates: list[str] = []
    for loc_key in ("primary_location", "best_oa_location"):
        loc = row.get(loc_key) if isinstance(row.get(loc_key), dict) else {}
        landing = str(loc.get("landing_page_url") or "").strip()
        if landing.startswith("http"):
            candidates.append(landing)
        pdf = str(loc.get("pdf_url") or "").strip()
        if pdf.startswith("http") and pdf.lower().endswith(".pdf"):
            # Prefer HTML landing for clicks; PDF is still better than a dead doi.
            candidates.append(pdf)

    oa = row.get("open_access") if isinstance(row.get("open_access"), dict) else {}
    oa_url = str(oa.get("oa_url") or "").strip()
    if oa_url.startswith("http"):
        candidates.append(oa_url)

    for loc in row.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        landing = str(loc.get("landing_page_url") or "").strip()
        if landing.startswith("http"):
            candidates.append(landing)

    def _rank(u: str) -> tuple[int, int]:
        low = u.lower()
        if _is_data_deposit_url(u):
            return (9, len(u))
        if "doi.org/" in low:
            return (5, len(u))
        if low.endswith(".pdf"):
            return (2, len(u))
        return (1, len(u))

    good = [u for u in candidates if u and not _is_data_deposit_url(u) and "doi.org/" not in u.lower()]
    if good:
        good.sort(key=_rank)
        pick = good[0]
        return expand_doi_landing(pick) or pick

    doi_raw = row.get("doi") or ids.get("doi")
    expanded = expand_doi_landing(str(doi_raw) if doi_raw else None)
    if expanded and not _is_data_deposit_url(expanded):
        return expanded

    # Last resorts: data deposit / doi / OpenAlex id (still better than empty).
    if candidates:
        candidates.sort(key=_rank)
        return expand_doi_landing(candidates[0]) or candidates[0]
    if expanded:
        return expanded
    return str(row.get("id") or "").strip()


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
    # mailto improves OpenAlex politeness pool; keep short timeout to avoid UI hang.
    url = (
        "https://api.openalex.org/works"
        f"?filter=concepts.id:{concept_id}"
        "&sort=publication_date:desc"
        f"&per_page={max_results}"
        "&mailto=bagel@localhost"
    )
    with _client(timeout=25.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[PaperRecord] = []
    for row in data.get("results") or []:
        title = (row.get("display_name") or "").strip()
        link = prefer_paper_landing_url(row)
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
        # Prefer OA PDF landing when present (stored in raw for later download).
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
    """Search Semantic Scholar.

    Retries / skip are owned by ``jobs.source_guard`` (max 3) so this call is
    single-shot — avoids nested 3×3 sleeps on anonymous 429.
    """
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={quote_plus(query)}&limit={max_results}"
        "&fields=title,url,abstract,authors,year,externalIds,publicationDate"
    )
    settings = get_settings()
    headers = {"User-Agent": USER_AGENT}
    # Optional: SEMANTIC_SCHOLAR_API_KEY raises anonymous rate limits.
    api_key = (settings.semantic_scholar_api_key or "").strip()
    if api_key:
        headers["x-api-key"] = api_key

    with _client() as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 429:
            raise httpx.HTTPStatusError(
                "429 Too Many Requests for Semantic Scholar",
                request=resp.request,
                response=resp,
            )
        resp.raise_for_status()
        data = resp.json()

    out: list[PaperRecord] = []
    for row in data.get("data") or []:
        title = (row.get("title") or "").strip()
        link = row.get("url") or ""
        ext = row.get("externalIds") or {}
        if ext.get("ArXiv"):
            link = f"https://arxiv.org/abs/{ext['ArXiv']}"
        elif not link and ext.get("DOI"):
            link = expand_doi_landing(f"doi:{ext['DOI']}") or f"https://doi.org/{ext['DOI']}"
        elif link and "doi.org/" in link.lower():
            link = expand_doi_landing(link) or link
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


_ARXIV_ABS_RE = re.compile(
    r"(?:"
    r"arxiv\.org/(?:abs|pdf|html)/|"
    r"arxiv:|"
    r"huggingface\.co/papers/|"
    r"(?:^|[/:])hf:|"
    r"papers/"
    r")(?P<id>\d{4}\.\d{4,5})(?:v\d+)?",
    re.I,
)
_DOI_RE = re.compile(r"(?:doi\.org/|doi:)(?P<doi>10\.\S+)", re.I)


def extract_arxiv_id(url_or_id: str | None) -> str | None:
    text = (url_or_id or "").strip()
    if not text:
        return None
    m = _ARXIV_ABS_RE.search(text)
    if m:
        return m.group("id")
    # bare id or hf:id without path noise
    if re.fullmatch(r"(?:hf:)?\d{4}\.\d{4,5}(v\d+)?", text, flags=re.I):
        return re.sub(r"^(?:hf:)?", "", re.sub(r"v\d+$", "", text, flags=re.I), flags=re.I)
    # external_id forms: hf:2401.12345 / arxiv:2401.12345
    m2 = re.search(r"(?:^|:)(\d{4}\.\d{4,5})(?:v\d+)?$", text, flags=re.I)
    if m2 and ("hf" in text.lower() or "arxiv" in text.lower() or text.count(":") == 1):
        return m2.group(1)
    return None


def extract_doi(url_or_id: str | None) -> str | None:
    text = (url_or_id or "").strip()
    if not text:
        return None
    m = _DOI_RE.search(text)
    if not m:
        return None
    doi = m.group("doi").rstrip(").,;")
    return doi


def _oa_pdf_from_raw(raw: dict[str, Any] | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("pdf_url", "oa_url"):
        val = raw.get(key)
        if val and str(val).lower().endswith(".pdf"):
            return str(val)
    for nest_key in ("best_oa_location", "primary_location", "open_access"):
        nest = raw.get(nest_key)
        if isinstance(nest, dict):
            for key in ("pdf_url", "url_for_pdf", "oa_url"):
                val = nest.get(key)
                if not val:
                    continue
                s = str(val).strip()
                if key == "pdf_url" and s.startswith("http"):
                    return s
                if "pdf" in s.lower() or s.lower().endswith(".pdf"):
                    return s
    # OpenAlex locations list — first non-empty pdf_url wins
    for loc in raw.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        pdf = loc.get("pdf_url")
        if pdf and str(pdf).startswith("http"):
            return str(pdf)
    # Semantic Scholar
    oa = raw.get("openAccessPdf")
    if isinstance(oa, dict) and oa.get("url"):
        return str(oa["url"])
    return None


def resolve_pdf_url(
    *,
    page_url: str | None = None,
    external_id: str | None = None,
    raw: dict[str, Any] | None = None,
    stored_pdf_url: str | None = None,
) -> str | None:
    """Best-effort open-access PDF URL (prefer arXiv / stored / OA metadata)."""
    if stored_pdf_url and str(stored_pdf_url).strip().startswith("http"):
        return str(stored_pdf_url).strip()

    arxiv_id = (
        extract_arxiv_id(page_url)
        or extract_arxiv_id(external_id or "")
        or (extract_arxiv_id(str(raw.get("id") or "")) if isinstance(raw, dict) else None)
    )
    if not arxiv_id and isinstance(raw, dict):
        for key in ("arxiv_id", "ArXiv", "paperId"):
            arxiv_id = extract_arxiv_id(str(raw.get(key) or ""))
            if arxiv_id:
                break
        ext = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
        if not arxiv_id and ext.get("ArXiv"):
            arxiv_id = extract_arxiv_id(str(ext["ArXiv"]))

    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    oa = _oa_pdf_from_raw(raw)
    if oa:
        return oa

    if page_url and str(page_url).lower().endswith(".pdf"):
        return str(page_url)
    return None


def _extract_doi_any(
    *,
    page_url: str | None = None,
    external_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> str | None:
    doi = extract_doi(page_url) or extract_doi(external_id or "")
    if doi:
        return doi
    if not isinstance(raw, dict):
        return None
    doi = extract_doi(str(raw.get("doi") or ""))
    if doi:
        return doi
    ids = raw.get("ids")
    if isinstance(ids, dict):
        doi = extract_doi(str(ids.get("doi") or ""))
        if doi:
            return doi
    ext = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    if ext.get("DOI"):
        return extract_doi(f"doi:{ext['DOI']}") or str(ext["DOI"]).strip()
    return None


def resolve_pdf_url_with_fallback(
    *,
    page_url: str | None = None,
    external_id: str | None = None,
    raw: dict[str, Any] | None = None,
    stored_pdf_url: str | None = None,
    settings: Any | None = None,
    fetch_remote: bool = True,
) -> tuple[str | None, str | None]:
    """Return (pdf_url, hint). May call Zenodo / Unpaywall / landing HTML when needed."""
    pdf = resolve_pdf_url(
        page_url=page_url,
        external_id=external_id,
        raw=raw,
        stored_pdf_url=stored_pdf_url,
    )
    if pdf:
        return pdf, None

    if not fetch_remote:
        return None, "本地未解析到 PDF（需探测开放地址）"

    doi = _extract_doi_any(page_url=page_url, external_id=external_id, raw=raw)

    if doi and re.search(r"10\.5281/zenodo\.\d+", doi, re.I):
        zpdf = _zenodo_pdf(doi, settings=settings)
        if zpdf:
            return zpdf, "zenodo"

    if page_url and str(page_url).startswith("http"):
        land = _pdf_from_landing_page(str(page_url), settings=settings)
        if land:
            return land, "landing"
        # Landing HTML may expose a DOI even when item.url has none (data repos).
        if not doi:
            try:
                with _client(timeout=18.0) as client:
                    resp = client.get(str(page_url))
                    if resp.status_code < 400:
                        scraped = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", resp.text[:200_000], flags=re.I)
                        if scraped:
                            doi = scraped.group(0).rstrip(").,;&")
            except Exception:  # noqa: BLE001
                pass

    if doi:
        unpay = _unpaywall_pdf(doi, settings=settings)
        if unpay:
            return unpay, "unpaywall"
        if _is_data_deposit_url(page_url) or (doi and "/data." in doi.lower()):
            return None, (
                f"落地页像是数据仓储/补充材料（DOI {doi}），页面无论文 PDF"
                "（常见为 zip/txt）。请换出版社或 arXiv 落地页后再探测。"
            )
        return None, f"已识别 DOI {doi}，但未找到开放 PDF（可稍后重试或手动打开原文）"

    if _is_data_deposit_url(page_url):
        return None, "落地页为开放数据仓储，未发现论文 PDF（多为数据集 zip）"

    return None, (
        "未找到开放 PDF：无 arXiv / OpenAlex pdf_url / 落地页 citation_pdf_url。"
        "可稍后重试「探测开放 PDF」，或确认原文是否开放获取。"
    )


def _zenodo_pdf(doi: str, *, settings: Any | None = None) -> str | None:
    """Resolve PDF from Zenodo record API (DOI 10.5281/zenodo.{id})."""
    m = re.search(r"10\.5281/zenodo\.(\d+)", doi, re.I)
    if not m:
        return None
    record_id = m.group(1)
    try:
        with _client(timeout=20.0) as client:
            resp = client.get(f"https://zenodo.org/api/records/{record_id}")
            if resp.status_code >= 400:
                return None
            data = resp.json()
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list):
            return None
        pdfs: list[str] = []
        others: list[str] = []
        for f in files:
            if not isinstance(f, dict):
                continue
            key = str(f.get("key") or "")
            links = f.get("links") if isinstance(f.get("links"), dict) else {}
            href = (
                links.get("download")
                or links.get("self")
                or links.get("content")
                or ""
            )
            if not href:
                continue
            href = str(href)
            if key.lower().endswith(".pdf") or href.lower().endswith(".pdf"):
                pdfs.append(href)
            else:
                others.append(href)
        return (pdfs or others or [None])[0]
    except Exception:  # noqa: BLE001
        return None


_CITATION_PDF_RE = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_CITATION_PDF_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
    re.I,
)
_HREF_PDF_RE = re.compile(
    r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
    re.I,
)
_DC_ID_RE = re.compile(
    r'<meta[^>]+name=["\']DC\.identifier["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_DC_ID_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']DC\.identifier["\']',
    re.I,
)
_LINK_PDF_RE = re.compile(
    r'<link[^>]+type=["\']application/pdf["\'][^>]+href=["\']([^"\']+)["\']',
    re.I,
)
_LINK_PDF_RE2 = re.compile(
    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/pdf["\']',
    re.I,
)


def _abs_url(page_url: str, href: str) -> str:
    from urllib.parse import urljoin

    href = (href or "").strip()
    if href.startswith("http"):
        return href
    return urljoin(page_url, href)


def _pdf_from_landing_page(page_url: str, *, settings: Any | None = None) -> str | None:
    """Best-effort: citation_pdf_url / link[type=pdf] / .pdf href / DC.identifier."""
    try:
        with _client(timeout=18.0) as client:
            resp = client.get(page_url)
            if resp.status_code >= 400:
                return None
            ctype = (resp.headers.get("content-type") or "").lower()
            if "pdf" in ctype:
                return str(resp.url)
            text = resp.text[:400_000]
        for rx in (_CITATION_PDF_RE, _CITATION_PDF_RE2, _LINK_PDF_RE, _LINK_PDF_RE2):
            m = rx.search(text)
            if m:
                return _abs_url(page_url, m.group(1))
        for rx in (_DC_ID_RE, _DC_ID_RE2):
            for m in rx.finditer(text):
                val = (m.group(1) or "").strip()
                if val.lower().endswith(".pdf"):
                    return _abs_url(page_url, val)
        for m in _HREF_PDF_RE.finditer(text):
            return _abs_url(page_url, m.group(1))
        # Data deposits often only expose zip/txt — not a paper PDF.
        if _is_data_deposit_url(page_url) or (
            "supplementary data" in text.lower()[:2000] and ".pdf" not in text.lower()
        ):
            return None
    except Exception:  # noqa: BLE001
        return None
    return None


def _unpaywall_pdf(doi: str, *, settings: Any | None = None) -> str | None:
    """Best-effort Unpaywall lookup (degraded: returns None on failure)."""
    try:
        from bagel.settings import get_settings

        settings = settings or get_settings()
        email = (getattr(settings, "unpaywall_email", None) or "").strip() or "bagel@localhost"
        url = f"https://api.unpaywall.org/v2/{quote_plus(doi)}?email={quote_plus(email)}"
        with _client(timeout=20.0) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                return None
            data = resp.json()
        loc = data.get("best_oa_location") if isinstance(data, dict) else None
        if isinstance(loc, dict) and loc.get("url_for_pdf"):
            return str(loc["url_for_pdf"])
        if isinstance(loc, dict) and loc.get("url") and str(loc["url"]).lower().endswith(".pdf"):
            return str(loc["url"])
    except Exception:  # noqa: BLE001
        return None
    return None


def paper_has_resolvable_pdf(
    *,
    page_url: str | None = None,
    external_id: str | None = None,
    raw: dict[str, Any] | None = None,
    stored_pdf_url: str | None = None,
) -> bool:
    """Fast local check — no remote HTTP. Used to gate the download button."""
    return bool(
        resolve_pdf_url(
            page_url=page_url,
            external_id=external_id,
            raw=raw,
            stored_pdf_url=stored_pdf_url,
        )
    )


def download_pdf(
    pdf_url: str,
    dest: Path,
    *,
    timeout: float = 120.0,
) -> Path:
    """Download a PDF to ``dest`` (parent dirs created). Returns dest."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _client(timeout=timeout) as client:
        with client.stream("GET", pdf_url) as resp:
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            if "html" in ctype and "pdf" not in ctype:
                raise ValueError(f"期望 PDF，收到 HTML：{pdf_url[:120]}")
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(65536):
                    fh.write(chunk)
    if dest.stat().st_size < 500:
        raise ValueError(f"PDF 过小或下载失败（{dest.stat().st_size} bytes）")
    return dest
