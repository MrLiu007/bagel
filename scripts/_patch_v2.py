"""One-shot patch: add paper sources to seed + settings helpers + wire routes/tasks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"D:\coder\liuzm\new\ai-bagel")


def patch_seed() -> None:
    path = ROOT / "src/bagel/storage/seed.py"
    text = path.read_text(encoding="utf-8")
    if "DEFAULT_PAPER_SOURCES" in text:
        print("seed: already patched")
        return
    block = '''
DEFAULT_PAPER_SOURCES: list[dict] = [
    {"name": "arXiv cs.AI", "url": "arxiv:cs.AI", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 10},
    {"name": "arXiv cs.LG", "url": "arxiv:cs.LG", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 20},
    {"name": "arXiv cs.CL", "url": "arxiv:cs.CL", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 30},
    {"name": "arXiv cs.CV", "url": "arxiv:cs.CV", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 40},
    {"name": "arXiv cs.RO", "url": "arxiv:cs.RO", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 50},
    {"name": "Hugging Face Papers", "url": "hf:daily", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 60},
    {"name": "OpenAlex AI", "url": "openalex:C154945302", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 70},
    {"name": "Semantic Scholar LLM", "url": "s2:large language model", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 80},
]

'''
    if "DEFAULT_KEYWORDS" not in text:
        raise SystemExit("DEFAULT_KEYWORDS not found")
    text = text.replace("DEFAULT_KEYWORDS", block + "DEFAULT_KEYWORDS", 1)
    text = text.replace(
        'created = {"sources": 0, "keywords": 0, "github_queries": 0}',
        'created = {"sources": 0, "keywords": 0, "github_queries": 0, "paper_sources": 0}',
        1,
    )
    needle = "    session.flush()\n    return created"
    insert = '''    paper_count = session.scalar(
        select(func.count()).select_from(IntelSource).where(IntelSource.source_type == SourceType.PAPER)
    ) or 0
    if paper_count == 0:
        for row in DEFAULT_PAPER_SOURCES:
            session.add(
                IntelSource(
                    name=row["name"],
                    url=row["url"],
                    source_type=row.get("source_type", SourceType.PAPER),
                    region=row.get("region", Region.GLOBAL),
                    network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                    priority=row.get("priority", 100),
                    enabled=row.get("enabled", True),
                )
            )
            created["paper_sources"] = created.get("paper_sources", 0) + 1

    session.flush()
    return created'''
    if needle not in text:
        raise SystemExit("seed flush marker missing")
    text = text.replace(needle, insert, 1)
    path.write_text(text, encoding="utf-8")
    print("seed: patched")


def patch_settings_svc() -> None:
    path = ROOT / "src/bagel/services/settings_svc.py"
    text = path.read_text(encoding="utf-8")
    if "list_paper_sources" in text:
        print("settings_svc: already patched")
        return
    # fix import SourceType usage already present
    extra = '''

def list_paper_sources(session: Session) -> list[IntelSource]:
    return [s for s in SourceRepository(session).list_all() if s.source_type == SourceType.PAPER]


def default_paper_catalog() -> list[dict]:
    from bagel.storage.seed import DEFAULT_PAPER_SOURCES

    rows: list[dict] = []
    for row in DEFAULT_PAPER_SOURCES:
        rows.append(
            {
                "name": row["name"],
                "url": row["url"],
                "region": str(row.get("region", Region.GLOBAL)),
                "source_type": str(row.get("source_type", SourceType.PAPER)),
                "enabled": bool(row.get("enabled", True)),
            }
        )
    return rows


def add_paper_source(
    session: Session,
    *,
    name: str,
    url: str,
) -> IntelSource:
    cleaned_name = (name or "").strip()
    cleaned_url = (url or "").strip()
    if not cleaned_name or not cleaned_url:
        raise SettingsError("名称与 URL 不能为空")
    repo = SourceRepository(session)
    return repo.add(
        IntelSource(
            name=cleaned_name,
            url=cleaned_url,
            source_type=SourceType.PAPER,
            region=Region.GLOBAL,
            network_requirement=NetworkRequirement.PROXY_PREFERRED,
            priority=500,
            enabled=True,
        )
    )


def toggle_paper_source(session: Session, source_id: UUID, *, enabled: bool) -> IntelSource:
    return toggle_news_source(session, source_id, enabled=enabled)


def delete_paper_source(session: Session, source_id: UUID) -> None:
    delete_news_source(session, source_id)
'''
    path.write_text(text.rstrip() + "\n" + extra, encoding="utf-8")
    print("settings_svc: patched")


def patch_health_routes() -> None:
    path = ROOT / "src/bagel/web/routes/health.py"
    text = path.read_text(encoding="utf-8")
    text2 = text.replace(
        'active_tab = tab if tab in {"tags", "sources", "health"} else "tags"',
        'active_tab = tab if tab in {"tags", "sources", "papers", "health"} else "tags"',
    )
    if 'paper_sources = settings_svc.list_paper_sources' not in text2:
        text2 = text2.replace(
            "sources = settings_svc.list_news_sources(db) if active_tab == \"sources\" else []\n"
            "    default_catalog = settings_svc.default_source_catalog() if active_tab == \"sources\" else []",
            "sources = settings_svc.list_news_sources(db) if active_tab == \"sources\" else []\n"
            "    default_catalog = settings_svc.default_source_catalog() if active_tab == \"sources\" else []\n"
            "    paper_sources = settings_svc.list_paper_sources(db) if active_tab == \"papers\" else []\n"
            "    paper_catalog = settings_svc.default_paper_catalog() if active_tab == \"papers\" else []",
        )
        text2 = text2.replace(
            '"default_catalog": default_catalog,\n            "report": report,',
            '"default_catalog": default_catalog,\n'
            '            "paper_sources": paper_sources,\n'
            '            "paper_catalog": paper_catalog,\n'
            '            "report": report,',
        )
    if "@router.post(\"/settings/papers\")" not in text2:
        text2 = text2.rstrip() + '''


@router.post("/settings/papers")
async def add_paper_source(
    name: str = Form(...),
    url: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_paper_source(db, name=name, url=url)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=papers", status_code=303)


@router.post("/settings/papers/{source_id}/toggle")
async def toggle_paper_source(
    source_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_paper_source(db, source_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=papers", status_code=303)


@router.post("/settings/papers/{source_id}/delete")
async def delete_paper_source(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_paper_source(db, source_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=papers", status_code=303)
'''
    path.write_text(text2, encoding="utf-8")
    print("health routes: patched")


def patch_tasks() -> None:
    path = ROOT / "src/bagel/services/tasks.py"
    text = path.read_text(encoding="utf-8")
    if "collect_papers" in text:
        print("tasks: already patched")
        return
    text = text.replace(
        "from bagel.jobs.media import run_collect_media\n",
        "from bagel.jobs.media import run_collect_media\n"
        "from bagel.jobs.papers import run_collect_papers\n",
    )
    text = text.replace(
        'elif kind == "collect_media":\n',
        'elif kind == "collect_papers":\n'
        "                result = run_collect_papers(session, on_progress=on_progress)\n"
        '            elif kind == "collect_media":\n',
    )
    path.write_text(text, encoding="utf-8")
    print("tasks: patched")


def patch_main() -> None:
    path = ROOT / "src/bagel/main.py"
    text = path.read_text(encoding="utf-8")
    if "science_router" in text:
        print("main: already patched")
        return
    text = text.replace(
        "from bagel.web.routes.review import router as review_router\n",
        "from bagel.web.routes.review import router as review_router\n"
        "from bagel.web.routes.science import router as science_router\n",
    )
    text = text.replace(
        "    application.include_router(wechat_router)\n",
        "    application.include_router(wechat_router)\n"
        "    application.include_router(science_router)\n",
    )
    path.write_text(text, encoding="utf-8")
    print("main: patched")


def patch_collect_template() -> None:
    path = ROOT / "src/bagel/web/templates/collect.html"
    text = path.read_text(encoding="utf-8")
    if "collect_papers" not in text:
        text = text.replace(
            '<button data-kind="build_monthly_briefs" type="button">生成月度总结</button>',
            '<button data-kind="collect_papers" type="button">采集论文</button>\n'
            '    <button data-kind="build_monthly_briefs" type="button">生成月度总结</button>',
        )
        path.write_text(text, encoding="utf-8")
        print("collect.html: patched")
    else:
        print("collect.html: already patched")


def patch_media_template() -> None:
    path = ROOT / "src/bagel/web/templates/media.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "自媒体抓取走外部 <strong>MediaCrawler</strong>（密钥与路径只在 .env）。本页只选平台与关键词，不把各平台拆成顶栏 Tab。",
        "自媒体默认已启用 MediaCrawler（路径见 .env 中 MEDIA_CRAWLER_PATH，通常为 ./third_party/MediaCrawler）。本页只选平台与关键词。",
    )
    text = text.replace(
        "请在 .env 设置 <code>ENABLE_MEDIA_CRAWLER=true</code> 与 <code>MEDIA_CRAWLER_PATH</code> 后重启。",
        "默认已开启；若仍显示关闭，请检查 .env 是否被覆盖。",
    )
    path.write_text(text, encoding="utf-8")
    print("media.html: patched")


def patch_settings_template() -> None:
    path = ROOT / "src/bagel/web/templates/settings.html"
    text = path.read_text(encoding="utf-8")
    if 'tab=papers' not in text:
        text = text.replace(
            '<a href="/settings?tab=health" class="{% if tab == \'health\' %}on{% endif %}">系统状态</a>',
            '<a href="/settings?tab=papers" class="{% if tab == \'papers\' %}on{% endif %}">论文数据源</a>\n'
            '  <a href="/settings?tab=health" class="{% if tab == \'health\' %}on{% endif %}">系统状态</a>',
        )
    if "tab == 'papers'" not in text:
        block = '''
{% if tab == 'papers' %}
<div class="panel">
  <p class="hint">
    科普 Tab 使用的论文数据源。默认包含 arXiv（cs.AI/LG/CL/CV/RO）、Hugging Face Papers、OpenAlex、Semantic Scholar。
    URL 支持约定：<code>arxiv:cs.AI</code> / <code>hf:daily</code> / <code>openalex:C154945302</code> / <code>s2:query</code>。
  </p>
  <form class="inline" method="post" action="/settings/papers">
    <input type="text" name="name" placeholder="名称，如 arXiv cs.AI" required />
    <input type="text" name="url" placeholder="arxiv:cs.AI 或 https://…" required style="flex:2;min-width:220px;" />
    <button type="submit">添加</button>
  </form>
</div>
<div class="panel">
  {% if paper_sources %}
    {% for s in paper_sources %}
    <div class="row">
      <div>
        <div class="kw">{{ s.name }}
          <span class="badge {% if s.enabled %}on{% endif %}">{% if s.enabled %}ON{% else %}OFF{% endif %}</span>
        </div>
        <div class="meta" style="word-break:break-all;">{{ s.url }}</div>
      </div>
      <div class="actions">
        <form method="post" action="/settings/papers/{{ s.id }}/toggle">
          <input type="hidden" name="enabled" value="{% if s.enabled %}0{% else %}1{% endif %}" />
          <button type="submit">{% if s.enabled %}停用{% else %}启用{% endif %}</button>
        </form>
        <form method="post" action="/settings/papers/{{ s.id }}/delete" onsubmit="return confirm('确认删除该论文源？');">
          <button class="danger" type="submit">删除</button>
        </form>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <p class="empty">暂无论文源。可添加，或重启应用以写入默认种子。</p>
  {% endif %}
</div>
{% if paper_catalog %}
<details class="panel">
  <summary style="cursor:pointer;font-family:var(--font-mono);color:var(--accent-2);">查看内置默认论文源清单</summary>
  {% for d in paper_catalog %}
  <div class="row">
    <div>
      <div class="kw">{{ d.name }}</div>
      <div class="meta">{{ d.url }}</div>
    </div>
  </div>
  {% endfor %}
</details>
{% endif %}
{% endif %}

'''
        # insert before health tab block
        marker = "{% if tab == 'health'"
        if marker not in text:
            marker = "{% if tab == 'health' and report %}"
        if marker in text:
            text = text.replace(marker, block + marker, 1)
        else:
            text = text.replace("{% endblock %}", block + "{% endblock %}", 1)
    path.write_text(text, encoding="utf-8")
    print("settings.html: patched")


def patch_env() -> None:
    example = ROOT / ".env.example"
    text = example.read_text(encoding="utf-8") if example.exists() else ""
    if "ENABLE_MEDIA_CRAWLER=true" not in text:
        text = text.replace("ENABLE_MEDIA_CRAWLER=false", "ENABLE_MEDIA_CRAWLER=true")
        text = text.replace("MEDIA_CRAWLER_PATH=\n", "MEDIA_CRAWLER_PATH=./third_party/MediaCrawler\n")
        if "ENABLE_MEDIA_CRAWLER" not in text:
            text += "\nENABLE_MEDIA_CRAWLER=true\nMEDIA_CRAWLER_PATH=./third_party/MediaCrawler\n"
        example.write_text(text, encoding="utf-8")
        print(".env.example: patched")
    env = ROOT / ".env"
    et = env.read_text(encoding="utf-8") if env.exists() else ""
    if "ENABLE_MEDIA_CRAWLER" not in et:
        et += "\nENABLE_MEDIA_CRAWLER=true\nMEDIA_CRAWLER_PATH=./third_party/MediaCrawler\n"
    else:
        et = et.replace("ENABLE_MEDIA_CRAWLER=false", "ENABLE_MEDIA_CRAWLER=true")
        if "MEDIA_CRAWLER_PATH=" in et and "MEDIA_CRAWLER_PATH=./third_party/MediaCrawler" not in et:
            import re

            et = re.sub(r"MEDIA_CRAWLER_PATH=.*", "MEDIA_CRAWLER_PATH=./third_party/MediaCrawler", et)
        elif "MEDIA_CRAWLER_PATH=" not in et:
            et += "\nMEDIA_CRAWLER_PATH=./third_party/MediaCrawler\n"
    env.write_text(et, encoding="utf-8")
    print(".env: patched")


if __name__ == "__main__":
    patch_seed()
    patch_settings_svc()
    patch_health_routes()
    patch_tasks()
    patch_main()
    patch_collect_template()
    patch_media_template()
    patch_settings_template()
    patch_env()
    print("done")
