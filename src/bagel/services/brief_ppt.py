"""PPT / slide mode for brief projection pages (reveal.js).

Manuscript HTML is **reformatted** into short PPT-style pages (title + bullets),
not pasted as whole document chunks. Generated slides are cached under
``data/cache/brief_ppt/`` and reused until the brief content fingerprint changes.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from bagel.settings import Settings, get_settings

logger = logging.getLogger("bagel.brief_ppt")

_REVEAL_VER = "5.1.0"
_REVEAL_BASE = f"https://cdn.jsdelivr.net/npm/reveal.js@{_REVEAL_VER}/dist"

_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.I | re.S)
_H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.I | re.S)
_BLOCKQUOTE_RE = re.compile(r"<blockquote\b[^>]*>(.*?)</blockquote>", re.I | re.S)
_LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.I | re.S)
_P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；;!?\n])")

_SLIDE_BREAK_RE = re.compile(
    r"(?=<h2\b)|(?=<p\s+class=[\"']item-index[\"'])|(?=<h3\s+class=[\"']brief-item-title[\"'])",
    re.I,
)

_MAX_BULLETS = 5
_MAX_BULLET_CHARS = 72
_MAX_SLIDES = 80


def _strip_tags(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _truncate(text: str, limit: int = _MAX_BULLET_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[: max(1, limit - 1)].rstrip("，,、；; ")
    return cut + "…"


def _sentences_to_bullets(text: str, *, limit: int = 12) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip(" \t\r\n　·•-") for p in _SENT_SPLIT_RE.split(raw) if p.strip()]
    if len(parts) <= 1 and len(raw) > _MAX_BULLET_CHARS:
        # Long run-on without punctuation — soft-wrap by commas.
        parts = [p.strip() for p in re.split(r"[，,、]\s*", raw) if p.strip()]
    out: list[str] = []
    for p in parts:
        if len(p) < 2:
            continue
        out.append(_truncate(p))
        if len(out) >= limit:
            break
    return out


def _bullets_from_chunk(chunk: str) -> list[str]:
    bullets: list[str] = []
    for m in _LI_RE.finditer(chunk or ""):
        t = _strip_tags(m.group(1))
        if t:
            bullets.append(_truncate(t))
    if bullets:
        return bullets
    for m in _P_RE.finditer(chunk or ""):
        cls = ""
        open_tag = (chunk[m.start() : m.start() + 80] or "").lower()
        if "item-index" in open_tag or "class=" in open_tag and "item-index" in (m.group(0)[:80].lower()):
            continue
        t = _strip_tags(m.group(1))
        if not t or t.startswith("〔"):
            continue
        bullets.extend(_sentences_to_bullets(t, limit=8))
    if bullets:
        return bullets
    plain = _strip_tags(
        re.sub(r"<h[1-6]\b[^>]*>.*?</h[1-6]>", " ", chunk or "", flags=re.I | re.S)
    )
    return _sentences_to_bullets(plain, limit=8)


def _pack_bullet_slides(title: str, bullets: list[str], *, kicker: str = "") -> list[str]:
    title = _truncate(_strip_tags(title), 48) or "要点"
    clean = [b for b in bullets if b and b.strip()]
    if not clean:
        body = f"<h2>{html.escape(title)}</h2>"
        if kicker:
            body += f'<p class="ppt-kicker">{html.escape(_truncate(kicker, 100))}</p>'
        else:
            body += '<p class="ppt-kicker">（本节无提炼要点，见文档模式原文）</p>'
        return [body]

    slides: list[str] = []
    for i in range(0, len(clean), _MAX_BULLETS):
        chunk = clean[i : i + _MAX_BULLETS]
        heading = title if i == 0 else f"{title}（续）"
        lis = "".join(f"<li>{html.escape(b)}</li>" for b in chunk)
        parts = [f"<h2>{html.escape(heading)}</h2>"]
        if i == 0 and kicker:
            parts.append(f'<p class="ppt-kicker">{html.escape(_truncate(kicker, 90))}</p>')
        parts.append(f'<ul class="ppt-bullets">{lis}</ul>')
        slides.append("".join(parts))
    return slides


def _title_slide(deck_title: str, subtitle: str = "") -> str:
    parts = [f"<h1>{html.escape(deck_title or '汇总投屏')}</h1>"]
    if subtitle:
        parts.append(f'<p class="ppt-kicker">{html.escape(_truncate(subtitle, 120))}</p>')
    parts.append('<p class="ppt-foot">Bagel · PPT 模式 · 要点提炼</p>')
    return "".join(parts)


def compose_ppt_slides(article_html: str) -> list[str]:
    """Rewrite manuscript HTML into PPT-style slide bodies (short bullets)."""
    raw = (article_html or "").strip()
    if not raw:
        return ['<h1>暂无内容</h1><p class="ppt-kicker">请先生成汇总后再投屏</p>']

    deck_title = ""
    m1 = _H1_RE.search(raw)
    if m1:
        deck_title = _strip_tags(m1.group(1))
    subtitle = ""
    bq = _BLOCKQUOTE_RE.search(raw)
    if bq:
        subtitle = _strip_tags(bq.group(1))

    slides: list[str] = [_title_slide(deck_title or "汇总投屏", subtitle)]

    chunks = [c for c in _SLIDE_BREAK_RE.split(raw) if c and c.strip()]
    if not chunks:
        chunks = [raw]

    for chunk in chunks:
        head = chunk.lstrip()[:80].lower()
        # Skip pure title/blockquote prelude already used.
        if head.startswith("<h1") and not _H2_RE.search(chunk) and not _H3_RE.search(chunk):
            # leftover intro paragraphs under h1
            intro_bullets = _bullets_from_chunk(chunk)
            if intro_bullets and not any("投屏" in b or "终稿" in b for b in intro_bullets[:1]):
                slides.extend(_pack_bullet_slides("开篇提要", intro_bullets[:_MAX_BULLETS]))
            continue

        h2 = _H2_RE.search(chunk)
        h3 = _H3_RE.search(chunk)
        title = ""
        kicker = ""
        if h2:
            title = _strip_tags(h2.group(1))
        elif h3:
            title = _strip_tags(h3.group(1))
            idx = re.search(
                r'class=["\']item-index["\'][^>]*>(.*?)</p>',
                chunk,
                re.I | re.S,
            )
            if idx:
                kicker = _strip_tags(idx.group(1))
        else:
            title = "补充要点"

        bullets = _bullets_from_chunk(chunk)
        # Drop echo of the title itself.
        bullets = [b for b in bullets if b != title and b not in {kicker, deck_title}]
        slides.extend(_pack_bullet_slides(title, bullets, kicker=kicker))
        if len(slides) >= _MAX_SLIDES:
            slides.append(
                '<h2>后续内容已折叠</h2>'
                '<p class="ppt-kicker">条目较多，请用文档模式查看全文，或缩短汇总后再投屏。</p>'
            )
            break

    return slides[:_MAX_SLIDES]


def compose_ppt_slides_llm(article_html: str) -> list[str] | None:
    """Optional LLM rewrite into slide JSON; None on skip/failure."""
    from bagel.services.llm import LlmClient
    from bagel.settings import get_settings

    settings = get_settings()
    client = LlmClient(settings)
    if not client.available:
        return None

    plain = _strip_tags(article_html or "")
    if len(plain) < 40:
        return None
    # Keep prompt bounded.
    plain = plain[:12000]

    system = (
        "你是汇报 PPT 文案编辑。把中文汇总稿改写成适合投屏的幻灯片大纲。"
        "必须输出 JSON 对象，格式："
        '{"slides":[{"title":"短标题","bullets":["要点1","要点2"]}]}。'
        "规则：首页可用较长标题；每页最多 5 条要点；每条不超过 36 个汉字；"
        "不要粘贴大段原文；不要表格/代码；不要 markdown；不要解释。"
    )
    user = f"请将以下汇总改写成 PPT 幻灯片 JSON：\n\n{plain}"
    parsed, err = client.complete_json(system=system, user=user, temperature=0.2)
    if err or not isinstance(parsed, dict):
        return None
    rows = parsed.get("slides")
    if not isinstance(rows, list) or not rows:
        return None

    out: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        title = _strip_tags(str(row.get("title") or "")).strip() or (f"第 {i + 1} 页")
        bullets_raw = row.get("bullets") or row.get("points") or []
        if isinstance(bullets_raw, str):
            bullets_raw = [bullets_raw]
        bullets = [
            _truncate(_strip_tags(str(b)), 48)
            for b in bullets_raw
            if str(b).strip()
        ][:_MAX_BULLETS]
        if i == 0 and not bullets:
            out.append(_title_slide(title))
            continue
        out.extend(_pack_bullet_slides(title, bullets))
        if len(out) >= _MAX_SLIDES:
            break
    return out or None


def article_html_to_slides(article_html: str, *, use_llm: bool = True) -> list[str]:
    """Public entry: prefer LLM reformatting when available, else deterministic PPT pack."""
    if use_llm:
        try:
            llm_slides = compose_ppt_slides_llm(article_html)
            if llm_slides:
                return llm_slides
        except Exception:
            pass
    return compose_ppt_slides(article_html)


def ppt_content_fingerprint(
    *,
    markdown: str,
    title: str = "",
    item_count: int = 0,
    generated_at: datetime | str | None = None,
    template_version: str = "",
) -> str:
    """Stable hash so PPT cache invalidates when the brief body changes."""
    gen = ""
    if generated_at is not None:
        gen = generated_at.isoformat() if hasattr(generated_at, "isoformat") else str(generated_at)
    payload = "\n".join(
        [
            (title or "").strip(),
            str(int(item_count or 0)),
            (template_version or "").strip(),
            gen,
            (markdown or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


def ppt_cache_path(brief_id: UUID | str, *, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    root = Path(settings.data_dir) / "cache" / "brief_ppt"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{brief_id}.json"


def load_ppt_slides_cache(
    brief_id: UUID | str,
    fingerprint: str,
    *,
    settings: Settings | None = None,
) -> list[str] | None:
    path = ppt_cache_path(brief_id, settings=settings)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if str(raw.get("fingerprint") or "") != fingerprint:
        return None
    slides = raw.get("slides")
    if not isinstance(slides, list) or not slides:
        return None
    out = [str(s) for s in slides if str(s).strip()]
    return out or None


def save_ppt_slides_cache(
    brief_id: UUID | str,
    fingerprint: str,
    slides: Sequence[str],
    *,
    settings: Settings | None = None,
) -> Path:
    path = ppt_cache_path(brief_id, settings=settings)
    payload = {
        "fingerprint": fingerprint,
        "slides": list(slides),
        "slide_count": len(slides),
        "built_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def get_or_build_ppt_slides(
    article_html: str,
    *,
    brief_id: UUID | str,
    fingerprint: str,
    use_llm: bool = True,
    force: bool = False,
    settings: Settings | None = None,
) -> tuple[list[str], bool]:
    """Return (slides, from_cache). Builds and persists when missing/forced."""
    settings = settings or get_settings()
    if not force:
        cached = load_ppt_slides_cache(brief_id, fingerprint, settings=settings)
        if cached:
            return cached, True
    slides = article_html_to_slides(article_html, use_llm=use_llm)
    try:
        save_ppt_slides_cache(brief_id, fingerprint, slides, settings=settings)
    except OSError as exc:
        logger.warning("ppt cache save failed: %s", exc)
    return slides, False


def _slide_sections(slides: Sequence[str]) -> str:
    parts: list[str] = []
    for body in slides:
        # Inner wrapper gives Reveal a stable block to vertically center.
        parts.append(
            f'<section class="bagel-slide"><div class="slide-inner">{body}</div></section>'
        )
    return "\n".join(parts)


_PPT_THEME_CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Source+Sans+3:wght@400;600;700&display=swap");
:root {
  --ink: #e8eef2;
  --ink-soft: #c5d0da;
  --muted: #8b99a8;
  --paper: #0d1218;
  --panel: #15202a;
  --line: rgba(232,238,242,0.12);
  --accent: #3cb8a5;
  --accent-soft: rgba(60,184,165,0.16);
  --warn: #d4a35c;
  --font-display: "Fraunces", "Source Han Serif SC", "Songti SC", serif;
  --font-body: "Source Sans 3", "PingFang SC", "Microsoft YaHei", sans-serif;
}
@media (prefers-color-scheme: light) {
  :root {
    --ink: #15202b;
    --ink-soft: #3d4b58;
    --muted: #667687;
    --paper: #e6ebf0;
    --panel: #f7f9fb;
    --line: rgba(21,32,43,0.10);
    --accent: #1a8576;
    --accent-soft: rgba(26,133,118,0.12);
    --warn: #a87428;
  }
}
html, body {
  margin: 0; height: 100%;
  overflow: hidden;
  background: var(--paper);
  font-family: var(--font-body);
  color: var(--ink);
}
.ppt-bar {
  position: fixed; top: 0; left: 0; right: 0; z-index: 40;
  display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center;
  padding: 0.55rem 0.9rem;
  background: color-mix(in srgb, var(--paper) 82%, transparent);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(14px);
}
.ppt-bar a, .ppt-bar button {
  appearance: none; border: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  color: var(--ink-soft); border-radius: 999px; padding: 0.35rem 0.85rem;
  font-size: 0.82rem; font-weight: 600; text-decoration: none; cursor: pointer;
}
.ppt-bar a:hover, .ppt-bar button:hover { color: var(--ink); border-color: var(--accent); }
.ppt-bar button.primary, .ppt-bar a.primary {
  border-color: transparent; background: var(--accent); color: #041512; font-weight: 700;
}
.ppt-bar .meta {
  margin-left: auto; color: var(--muted); font-size: 0.78rem;
  font-family: ui-monospace, monospace;
  max-width: min(46vw, 28rem); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ppt-hint {
  position: fixed; bottom: 0.45rem; left: 0; right: 0; z-index: 35;
  text-align: center; margin: 0; color: var(--muted);
  font-size: 0.72rem; font-family: ui-monospace, monospace; letter-spacing: 0.03em;
  pointer-events: none;
}
.reveal {
  position: absolute !important;
  top: 3.05rem !important;
  left: 0 !important;
  right: 0 !important;
  width: 100% !important;
  height: calc(100vh - 4.2rem) !important;
  background:
    radial-gradient(1100px 520px at 12% -8%, rgba(60,184,165,0.18), transparent 58%),
    var(--paper);
}
.reveal .slides {
  text-align: center;
  width: 100%;
  height: 100%;
}
/*
  Reveal center:true writes inline top offsets based on content height.
  That fights full-height slides and pins copy to the bottom — disable it
  in JS and center ourselves with flex + top:0 !important.
*/
.reveal .slides section.bagel-slide {
  position: absolute !important;
  top: 0 !important;
  left: 0 !important;
  box-sizing: border-box !important;
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
  text-align: center;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--panel) 94%, var(--accent)), var(--panel));
  border: 1px solid var(--line);
  border-radius: 0;
  box-shadow: none;
}
.reveal .slides section.bagel-slide.present {
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
  visibility: visible !important;
  z-index: 2;
}
.reveal .slides section.bagel-slide.past,
.reveal .slides section.bagel-slide.future {
  display: none !important;
}
.reveal .slides section.bagel-slide::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  z-index: 2;
  pointer-events: none;
  background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 40%, var(--warn)), transparent 88%);
}
.reveal .slides section.bagel-slide .slide-inner {
  box-sizing: border-box;
  position: relative;
  z-index: 1;
  width: min(86%, 52rem);
  max-width: 52rem;
  max-height: 86%;
  overflow: auto;
  margin: 0;
  padding: 2.2rem 2rem;
  text-align: left;
  flex: 0 1 auto;
}
.reveal h1 {
  font-family: var(--font-display);
  font-size: 2.85rem; line-height: 1.18; letter-spacing: -0.02em;
  margin: 0 0 0.95rem; color: var(--ink); text-transform: none;
  text-align: left;
}
.reveal h2 {
  font-family: var(--font-display);
  font-size: 2.05rem; line-height: 1.28; letter-spacing: -0.015em;
  margin: 0 0 1.05rem; padding-bottom: 0.45rem;
  border-bottom: 1px solid var(--line); color: var(--ink);
  text-transform: none;
  text-align: left;
}
.reveal h2::before {
  content: ""; display: inline-block; width: 0.55rem; height: 0.55rem;
  margin-right: 0.55rem; border-radius: 2px; background: var(--accent);
  transform: translateY(-0.08em);
}
.reveal .ppt-kicker {
  font-size: 1.2rem; line-height: 1.45; color: var(--muted); margin: 0 0 0.95rem;
  text-align: left;
}
.reveal .ppt-foot {
  margin-top: 1.25rem; font-size: 0.9rem; color: var(--muted);
  font-family: ui-monospace, monospace; letter-spacing: 0.04em;
  text-align: left;
}
.reveal ul.ppt-bullets {
  list-style: none; margin: 0.15rem 0 0; padding: 0;
  width: 100%;
  text-align: left;
}
.reveal ul.ppt-bullets li {
  position: relative;
  font-size: 1.45rem; line-height: 1.48; color: var(--ink-soft);
  margin: 0 0 0.85rem; padding-left: 1.45rem;
  max-width: none;
  width: 100%;
}
.reveal ul.ppt-bullets li::before {
  content: "";
  position: absolute; left: 0; top: 0.55em;
  width: 0.55rem; height: 0.55rem; border-radius: 2px;
  background: var(--accent);
}
.reveal .controls { color: var(--accent); }
.reveal .progress span { background: var(--accent); }
.reveal .slide-number {
  color: var(--muted); background: transparent; font-size: 0.8rem;
  right: 18px; bottom: 12px;
}
.ppt-loader {
  min-height: 100vh; display: grid; place-items: center; padding: 2rem;
  background:
    radial-gradient(900px 420px at 10% -10%, rgba(60,184,165,0.16), transparent 55%),
    var(--paper);
}
.ppt-loader-card {
  width: min(420px, 92vw);
  padding: 1.6rem 1.5rem 1.4rem;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--panel);
  box-shadow: 0 22px 50px rgba(0,0,0,0.28);
}
.ppt-loader-card h1 {
  font-family: var(--font-display);
  font-size: 1.45rem; margin: 0 0 0.45rem; color: var(--ink);
}
.ppt-loader-card .sub { color: var(--muted); font-size: 0.92rem; margin: 0 0 1.1rem; }
.ppt-loader .bar {
  height: 8px; border-radius: 999px; background: var(--line); overflow: hidden;
}
.ppt-loader .bar > span {
  display: block; height: 100%; width: 8%;
  background: linear-gradient(90deg, var(--accent), var(--warn));
  border-radius: inherit;
  transition: width 0.35s ease;
}
.ppt-loader .meta {
  margin-top: 0.75rem; color: var(--ink-soft); font-size: 0.88rem;
}
.ppt-loader .hint {
  margin-top: 0.45rem; color: var(--muted); font-size: 0.78rem;
  font-family: ui-monospace, monospace;
}
.ppt-loader a {
  display: inline-block; margin-top: 1rem; color: var(--accent);
  font-size: 0.85rem; text-decoration: none;
}
"""


def build_ppt_loading_html(
    *,
    title: str,
    build_url: str,
    back_url: str,
    meta_line: str = "",
    cached_hint: bool = False,
) -> str:
    """Friendly progress shell while PPT slides are composed."""
    deck_title = (title or "汇总 PPT").strip()
    hint0 = (
        "检测到缓存失效或强制重建，正在重新生成…"
        if cached_hint
        else "首次生成后会缓存，下次打开可直接复用"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(deck_title)} · 准备 PPT</title>
<style>
{_PPT_THEME_CSS}
</style>
</head>
<body>
<main class="ppt-loader">
  <div class="ppt-loader-card">
    <h1>正在生成 PPT</h1>
    <p class="sub">{html.escape(meta_line or deck_title)}</p>
    <div class="bar"><span id="bar"></span></div>
    <div class="meta" id="meta">读取汇总稿…</div>
    <div class="hint" id="hint">{html.escape(hint0)}</div>
    <a href="{html.escape(back_url)}">← 取消，返回汇总</a>
  </div>
</main>
<script>
(function () {{
  const bar = document.getElementById('bar');
  const meta = document.getElementById('meta');
  const hint = document.getElementById('hint');
  const steps = [
    [12, '读取汇总稿…', '解析章节与条目'],
    [28, '提炼要点…', '去掉大段原文，改成短句'],
    [48, '分页排版…', '每页控制在 5 条以内'],
    [68, '生成幻灯片…', '若已配置 LLM 会再精炼一轮'],
    [82, '仍在处理…', '内容较多时需要多几秒'],
  ];
  let i = 0;
  const tick = setInterval(() => {{
    if (i >= steps.length) return;
    const [pct, m, h] = steps[i++];
    bar.style.width = pct + '%';
    meta.textContent = m;
    hint.textContent = h;
  }}, 700);
  const buildUrl = {json.dumps(build_url)};
  const started = Date.now();
  fetch(buildUrl, {{ credentials: 'same-origin' }})
    .then(async (r) => {{
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.text();
    }})
    .then((htmlText) => {{
      clearInterval(tick);
      bar.style.width = '100%';
      meta.textContent = '完成 · ' + Math.round((Date.now() - started) / 1000) + 's';
      hint.textContent = '已缓存，下次可直接打开 · 正在打开放映…';
      setTimeout(() => {{
        document.open();
        document.write(htmlText);
        document.close();
      }}, 180);
    }})
    .catch((err) => {{
      clearInterval(tick);
      bar.style.width = '100%';
      meta.textContent = '生成失败';
      hint.textContent = String(err && err.message || err || '未知错误');
    }});
}})();
</script>
</body>
</html>"""


def build_brief_ppt_html(
    *,
    title: str,
    article_html: str,
    back_url: str,
    doc_mode_url: str,
    export_html_url: str,
    export_md_url: str,
    meta_line: str = "",
    use_llm: bool = True,
    slides: Sequence[str] | None = None,
    rebuild_url: str = "",
    from_cache: bool = False,
) -> str:
    """Self-contained reveal.js deck from reformatted PPT slides."""
    if slides is None:
        slides = article_html_to_slides(article_html, use_llm=use_llm)
    deck_title = (title or "").strip()
    if not deck_title:
        m = _H1_RE.search(article_html or "")
        deck_title = _strip_tags(m.group(1)) if m else "汇总投屏"
    sections = _slide_sections(slides)
    n = len(slides)
    meta_js = json.dumps(meta_line or "")
    back_js = json.dumps(back_url)
    cache_badge = " · 缓存" if from_cache else ""
    rebuild_link = (
        f'<a href="{html.escape(rebuild_url)}">重新生成</a>' if rebuild_url else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(deck_title)} · PPT</title>
<link rel="stylesheet" href="{_REVEAL_BASE}/reveal.css"/>
<link rel="stylesheet" href="{_REVEAL_BASE}/theme/black.css" id="theme"/>
<style>
{_PPT_THEME_CSS}
</style>
</head>
<body>
<header class="ppt-bar">
  <a href="{html.escape(back_url)}">← 返回汇总</a>
  <a href="{html.escape(doc_mode_url)}">文档模式</a>
  <button type="button" id="ppt-prev" aria-label="上一页">上一页</button>
  <button type="button" id="ppt-next" class="primary" aria-label="下一页">下一页</button>
  <span class="meta" id="ppt-meta">{html.escape(meta_line)} · {n} 页{html.escape(cache_badge)}</span>
  {rebuild_link}
  <a href="{html.escape(export_html_url)}">下载 HTML</a>
  <a href="{html.escape(export_md_url)}">Markdown</a>
</header>
<div class="reveal">
  <div class="slides">
{sections}
  </div>
</div>
<p class="ppt-hint">Bagel · PPT 模式 · ←/→ 或按钮翻页 · Esc 返回汇总 · F 全屏</p>
<script src="{_REVEAL_BASE}/reveal.js"></script>
<script type="module">
  const deck = Reveal;
  const fixSlideTops = () => {{
    // Reveal may re-apply inline top after layout; pin slides to the viewport.
    document.querySelectorAll(".reveal .slides section.bagel-slide").forEach((sec) => {{
      sec.style.top = "0px";
      sec.style.marginTop = "0px";
    }});
  }};
  deck.initialize({{
    hash: true,
    controls: true,
    controlsTutorial: false,
    progress: true,
    slideNumber: "c/t",
    center: false,
    width: 1920,
    height: 1080,
    margin: 0.04,
    minScale: 0.25,
    maxScale: 1.5,
    transition: "fade",
    backgroundTransition: "fade",
    keyboard: true,
    touch: true,
    navigationMode: "linear",
    disableLayout: false,
  }}).then(() => {{
    const syncMeta = () => {{
      const idx = deck.getIndices().h + 1;
      const total = deck.getTotalSlides();
      const el = document.getElementById("ppt-meta");
      if (el) {{
        const base = {meta_js};
        const cache = {json.dumps(cache_badge)};
        el.textContent = (base ? base + " · " : "") + idx + " / " + total + cache;
      }}
      fixSlideTops();
    }};
    syncMeta();
    fixSlideTops();
    deck.on("slidechanged", syncMeta);
    deck.on("resize", fixSlideTops);
    document.getElementById("ppt-prev")?.addEventListener("click", () => deck.prev());
    document.getElementById("ppt-next")?.addEventListener("click", () => deck.next());
  }});
  document.addEventListener("keydown", (e) => {{
    if (e.key === "Escape") location.href = {back_js};
    if ((e.key === "f" || e.key === "F") && !e.metaKey && !e.ctrlKey) {{
      const el = document.documentElement;
      if (!document.fullscreenElement) el.requestFullscreen?.();
      else document.exitFullscreen?.();
    }}
  }});
</script>
</body>
</html>"""
