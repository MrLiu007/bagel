"""Settings routes — filter tags + news sources + system health."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.services import auth as auth_svc
from bagel.services import settings_svc
from bagel.services.health import run_health_checks
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import templates

router = APIRouter(tags=["health"])


def _settings_redirect(db: Session, tab: str, *, saved: str | None = "1") -> RedirectResponse:
    """PRG redirect after settings mutation.

    Commit *before* returning 303 so the follow-up GET cannot race the
    dependency-teardown commit (browser would otherwise see stale tags).
    """
    db.commit()
    q = f"/settings?tab={quote(tab, safe='')}"
    if saved:
        q += f"&saved={quote(saved, safe='')}"
    resp = RedirectResponse(url=q, status_code=303)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@router.get("/settings", response_class=HTMLResponse, response_model=None)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    tab: str = Query("sources"),
    saved: str | None = Query(None),
):
    if tab == "tags":
        # Legacy bookmark: 过滤标签已并入新闻数据源兴趣标签。
        return RedirectResponse(url="/settings?tab=sources", status_code=303)
    active_tab = tab if tab in {
        "sources",
        "github",
        "papers",
        "education",
        "models",
        "stocks",
        "excludes",
        "schedule",
        "cli",
        "config",
        "health",
        "users",
    } else "sources"
    report = run_health_checks(db) if active_tab == "health" else None
    sources = settings_svc.list_news_sources(db) if active_tab == "sources" else []
    default_catalog = settings_svc.default_source_catalog() if active_tab == "sources" else []
    paper_sources = settings_svc.list_paper_sources(db) if active_tab == "papers" else []
    paper_catalog = settings_svc.default_paper_catalog() if active_tab == "papers" else []
    education_sources = settings_svc.list_education_sources(db) if active_tab == "education" else []
    education_catalog = settings_svc.default_education_catalog() if active_tab == "education" else []
    model_sources = settings_svc.list_model_sources(db) if active_tab == "models" else []
    model_catalog = settings_svc.default_model_catalog() if active_tab == "models" else []
    stock_sources = settings_svc.list_stock_sources(db) if active_tab == "stocks" else []
    stock_catalog = settings_svc.default_stock_catalog() if active_tab == "stocks" else []
    github_queries = settings_svc.list_github_queries(db) if active_tab == "github" else []
    users = auth_svc.list_users(db) if active_tab == "users" else []

    from bagel.pipeline.keyword_scopes import (
        ALL_SCOPES,
        INCLUDE_SCOPES,
        SCOPE_LABELS,
        TAB_TO_SCOPE,
        effective_scopes,
    )

    include_scope = TAB_TO_SCOPE.get(active_tab)
    include_tags = (
        settings_svc.list_filter_tags(db, scope=include_scope) if include_scope else []
    )
    exclude_tags = settings_svc.list_exclude_tags(db) if active_tab == "excludes" else []
    exclude_scope_meta = [
        {
            "rule": rule,
            "scopes": effective_scopes(rule),
            "labels": settings_svc.scope_labels_for_rule(rule),
        }
        for rule in exclude_tags
    ]

    schedule_cfg = None
    schedule_status = None
    schedule_options = None
    cli_status = None
    runtime_cfg = None
    env_groups = None
    env_path = None
    config_message = None
    if active_tab == "schedule":
        from bagel.jobs.scheduler import scheduler_status
        from bagel.services.runtime_config import (
            SCHEDULE_INTERVAL_OPTIONS,
            load_runtime_config,
        )

        schedule_cfg = load_runtime_config()
        schedule_status = scheduler_status()
        schedule_options = list(SCHEDULE_INTERVAL_OPTIONS)
    if active_tab == "cli":
        from bagel.integrations import feishu_cli
        from bagel.services.runtime_config import load_runtime_config

        runtime_cfg = load_runtime_config()
        cli_status = feishu_cli.status().as_dict()
    if active_tab == "config":
        from bagel.pipeline.paths import display_path
        from bagel.services import env_config as env_cfg
        from bagel.services import user_config as user_cfg

        uid = request.session.get("user_id")
        is_admin = bool(request.session.get("is_admin"))
        env_groups = user_cfg.catalog_for_ui(uid, is_admin=is_admin)
        env_path = display_path(env_cfg.resolve_env_path())
        config_message = request.query_params.get("msg")

    settings_message = "已保存，列表已更新。" if saved else None

    response = templates.TemplateResponse(
        request,
        "settings.html",
        {
            "title": "系统设置",
            "active": "settings",
            "nav": NAV_ITEMS,
            "tab": active_tab,
            "settings_message": settings_message,
            "include_tags": include_tags,
            "include_scope": include_scope,
            "include_scope_label": SCOPE_LABELS.get(include_scope or "", ""),
            "exclude_tags": exclude_tags,
            "exclude_scope_meta": exclude_scope_meta,
            "all_scopes": list(ALL_SCOPES),
            "include_scopes": list(INCLUDE_SCOPES),
            "scope_labels": SCOPE_LABELS,
            "sources": sources,
            "default_catalog": default_catalog,
            "paper_sources": paper_sources,
            "paper_catalog": paper_catalog,
            "education_sources": education_sources,
            "education_catalog": education_catalog,
            "model_sources": model_sources,
            "model_catalog": model_catalog,
            "stock_sources": stock_sources,
            "stock_catalog": stock_catalog,
            "github_queries": github_queries,
            "report": report,
            "users": users,
            "is_admin": bool(request.session.get("is_admin")),
            "current_username": request.session.get("username"),
            "schedule_cfg": schedule_cfg,
            "schedule_status": schedule_status,
            "schedule_options": schedule_options,
            "runtime_cfg": runtime_cfg,
            "cli_status": cli_status,
            "env_groups": env_groups,
            "env_path": env_path,
            "config_message": config_message,
        },
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/settings/health", response_class=HTMLResponse)
async def settings_health() -> RedirectResponse:
    return RedirectResponse(url="/settings?tab=health", status_code=303)


@router.post("/settings/tags")
async def add_tag(
    keyword: str = Form(...),
    scope: str = Form("news"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_filter_tag(db, keyword, scope=scope)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return _settings_redirect(db, settings_svc.redirect_tab_for_scope(scope))


@router.post("/settings/tags/{rule_id}/toggle")
async def toggle_tag(
    rule_id: UUID,
    enabled: str = Form("1"),
    scope: str = Form("news"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_filter_tag(db, rule_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return _settings_redirect(db, settings_svc.redirect_tab_for_scope(scope))


@router.post("/settings/tags/{rule_id}/delete")
async def delete_tag(
    rule_id: UUID,
    scope: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_filter_tag(db, rule_id, scope=scope or None)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    tab = settings_svc.redirect_tab_for_scope(scope) if scope else "sources"
    return _settings_redirect(db, tab)


@router.post("/settings/excludes")
async def add_exclude(
    request: Request,
    keyword: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    scopes = [str(v) for v in form.getlist("scopes")]
    try:
        settings_svc.add_exclude_tag(db, keyword, scopes=scopes)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return _settings_redirect(db, "excludes")


@router.post("/settings/excludes/{rule_id}/scopes")
async def update_exclude_scopes(
    rule_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    scopes = [str(v) for v in form.getlist("scopes")]
    try:
        settings_svc.update_exclude_tag(db, rule_id, scopes=scopes)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return _settings_redirect(db, "excludes")


@router.post("/settings/excludes/{rule_id}/toggle")
async def toggle_exclude(
    rule_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_exclude_tag(db, rule_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return _settings_redirect(db, "excludes")


@router.post("/settings/excludes/{rule_id}/delete")
async def delete_exclude(
    rule_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_exclude_tag(db, rule_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return _settings_redirect(db, "excludes")


@router.post("/settings/github/{query_id}/toggle")
async def toggle_github_query(
    query_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_github_query(db, query_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=github", status_code=303)


@router.post("/settings/sources")
async def add_source(
    name: str = Form(...),
    url: str = Form(...),
    region: str = Form("CN"),
    source_type: str = Form("RSS"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_news_source(
            db, name=name, url=url, region=region, source_type=source_type
        )
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=sources", status_code=303)


@router.post("/settings/sources/{source_id}/toggle")
async def toggle_source(
    source_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_news_source(db, source_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=sources", status_code=303)


@router.post("/settings/sources/{source_id}/delete")
async def delete_source(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_news_source(db, source_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=sources", status_code=303)


@router.get("/api/health/detail")
async def health_detail(db: Session = Depends(get_db)) -> JSONResponse:
    report = run_health_checks(db)
    return JSONResponse(
        {
            "can_run": report.can_run,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "message": c.message,
                    "degraded": c.degraded,
                }
                for c in report.checks
            ],
        }
    )


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


@router.post("/settings/education")
async def add_education_source(
    name: str = Form(...),
    url: str = Form(...),
    region: str = Form("GLOBAL"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_education_source(db, name=name, url=url, region=region)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=education", status_code=303)


@router.post("/settings/education/{source_id}/toggle")
async def toggle_education_source(
    source_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_education_source(db, source_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=education", status_code=303)


@router.post("/settings/education/{source_id}/delete")
async def delete_education_source(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_education_source(db, source_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=education", status_code=303)


@router.post("/settings/models")
async def add_model_source(
    name: str = Form(...),
    url: str = Form(...),
    region: str = Form("GLOBAL"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_model_source(db, name=name, url=url, region=region)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=models", status_code=303)


@router.post("/settings/models/{source_id}/toggle")
async def toggle_model_source(
    source_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_model_source(db, source_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=models", status_code=303)


@router.post("/settings/models/{source_id}/delete")
async def delete_model_source(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_model_source(db, source_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=models", status_code=303)


@router.post("/settings/stocks")
async def add_stock_source(
    name: str = Form(...),
    url: str = Form(...),
    region: str = Form("GLOBAL"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.add_stock_source(db, name=name, url=url, region=region)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=stocks", status_code=303)


@router.post("/settings/stocks/{source_id}/toggle")
async def toggle_stock_source(
    source_id: UUID,
    enabled: str = Form("1"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.toggle_stock_source(db, source_id, enabled=enabled in {"1", "true", "on"})
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=stocks", status_code=303)


@router.post("/settings/stocks/{source_id}/delete")
async def delete_stock_source(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_stock_source(db, source_id)
    except settings_svc.SettingsError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url="/settings?tab=stocks", status_code=303)


@router.post("/settings/schedule")
async def save_schedule(
    enable_scheduler: str | None = Form(None),
    schedule_interval_minutes: int = Form(30),
    schedule_jitter_seconds: int = Form(120),
    schedule_collect_news: str | None = Form(None),
    schedule_collect_github: str | None = Form(None),
    schedule_collect_stocks: str | None = Form(None),
    schedule_collect_models: str | None = Form(None),
    enable_keyword_growth: str | None = Form(None),
) -> RedirectResponse:
    from bagel.jobs.scheduler import reload_scheduler_jobs
    from bagel.services.runtime_config import (
        SCHEDULE_INTERVAL_OPTIONS,
        update_runtime_config,
    )

    minutes = int(schedule_interval_minutes)
    if minutes not in SCHEDULE_INTERVAL_OPTIONS:
        raise HTTPException(status_code=400, detail="不支持的拉取间隔")
    jitter = max(0, min(600, int(schedule_jitter_seconds)))
    update_runtime_config(
        enable_scheduler=enable_scheduler in {"1", "true", "on"},
        schedule_interval_minutes=minutes,
        schedule_jitter_seconds=jitter,
        schedule_collect_news=schedule_collect_news in {"1", "true", "on"},
        schedule_collect_github=schedule_collect_github in {"1", "true", "on"},
        schedule_collect_stocks=schedule_collect_stocks in {"1", "true", "on"},
        schedule_collect_models=schedule_collect_models in {"1", "true", "on"},
        enable_keyword_growth=enable_keyword_growth in {"1", "true", "on"},
    )
    reload_scheduler_jobs()
    return RedirectResponse(url="/settings?tab=schedule", status_code=303)


@router.post("/settings/cli")
async def save_cli(
    enable_feishu_cli: str | None = Form(None),
    feishu_cli_bin: str = Form("lark-cli"),
    feishu_webhook_url: str = Form(""),
    feishu_push_after_collect: str | None = Form(None),
) -> RedirectResponse:
    from bagel.services.runtime_config import update_runtime_config

    update_runtime_config(
        enable_feishu_cli=enable_feishu_cli in {"1", "true", "on"},
        feishu_cli_bin=(feishu_cli_bin or "lark-cli").strip() or "lark-cli",
        feishu_webhook_url=(feishu_webhook_url or "").strip(),
        feishu_push_after_collect=feishu_push_after_collect in {"1", "true", "on"},
    )
    return RedirectResponse(url="/settings?tab=cli", status_code=303)


@router.post("/settings/cli/feishu-test")
async def test_feishu(
    text: str = Form("贝果 CLI 测试消息"),
) -> RedirectResponse:
    from bagel.integrations import feishu_cli

    result = feishu_cli.send_text(text)
    if not result.ok:
        raise HTTPException(
            status_code=400,
            detail=result.error or result.stderr or "发送失败",
        )
    return RedirectResponse(url="/settings?tab=cli", status_code=303)


@router.post("/settings/cli/feishu-digest")
async def feishu_digest_push(
    kind: str = Form("yesterday"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    from bagel.integrations import feishu_cli

    key = (kind or "yesterday").strip().lower()
    try:
        if key == "yesterday":
            result, _meta = feishu_cli.push_yesterday_digest(db)
        elif key == "week":
            result, _meta = feishu_cli.push_week_briefs_digest(db, which="both")
        elif key == "week-this":
            result, _meta = feishu_cli.push_week_briefs_digest(db, which="this")
        elif key == "week-last":
            result, _meta = feishu_cli.push_week_briefs_digest(db, which="last")
        else:
            raise HTTPException(status_code=400, detail="未知推送类型")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)[:300]) from exc
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or result.stderr or "推送失败")
    return RedirectResponse(url="/settings?tab=cli", status_code=303)


@router.post("/settings/config")
async def save_env_config(request: Request) -> RedirectResponse:
    from bagel.services import env_config as env_cfg
    from bagel.services import user_config as user_cfg

    form = await request.form()
    uid = request.session.get("user_id")
    is_admin = bool(request.session.get("is_admin"))
    updates: dict[str, str] = {}
    system_updates: dict[str, str] = {}
    for field in env_cfg.ENV_CATALOG:
        if field.key in user_cfg.SYSTEM_ENV_KEYS:
            if not is_admin:
                continue
            if field.type == "bool":
                system_updates[field.key] = (
                    "true" if form.get(field.key) in {"1", "true", "on"} else "false"
                )
            elif field.key in form:
                system_updates[field.key] = str(form.get(field.key) or "")
            continue
        if field.type == "bool":
            updates[field.key] = "true" if form.get(field.key) in {"1", "true", "on"} else "false"
        elif field.key in form:
            updates[field.key] = str(form.get(field.key) or "")
    try:
        if system_updates and is_admin:
            env_cfg.update_env_values(system_updates)
        if not uid:
            raise HTTPException(status_code=401, detail="请先登录后再保存个人配置")
        path = user_cfg.save_user_overrides(uid, updates)
    except env_cfg.EnvConfigError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    msg = quote(
        f"已保存个人配置（{path.name}）；未改动的项仍使用系统默认。"
        + (" 系统项已写入 .env，部分需重启。" if system_updates and is_admin else ""),
        safe="",
    )
    return RedirectResponse(url=f"/settings?tab=config&msg={msg}", status_code=303)


@router.post("/settings/users")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    try:
        auth_svc.create_user(
            db,
            username=username,
            password=password,
            is_admin=is_admin in {"1", "true", "on"},
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/settings?tab=users", status_code=303)


@router.post("/settings/users/{user_id}/password")
async def change_user_password(
    request: Request,
    user_id: UUID,
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    user = auth_svc.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    current = request.session.get("user_id")
    is_admin = bool(request.session.get("is_admin"))
    if not is_admin and str(user.id) != str(current):
        raise HTTPException(status_code=403, detail="只能修改自己的密码")
    auth_svc.update_password(db, user, password)
    db.commit()
    return RedirectResponse(url="/settings?tab=users", status_code=303)


@router.post("/settings/users/{user_id}/toggle")
async def toggle_user(
    request: Request,
    user_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    user = auth_svc.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.username == request.session.get("username"):
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")
    auth_svc.set_active(db, user, not user.is_active)
    db.commit()
    return RedirectResponse(url="/settings?tab=users", status_code=303)
