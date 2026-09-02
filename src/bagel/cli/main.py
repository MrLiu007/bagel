"""CLI entry: `uv run bagel ...`

- In-process commands: Typer + Rich
- External binaries (Feishu etc.): integrations.cli_runtime + provider adapters
"""

from __future__ import annotations

import subprocess

import uvicorn
import typer
from rich.console import Console
from rich.table import Table

from bagel import __version__
from bagel.settings import get_settings

app = typer.Typer(
    name="bagel",
    help="贝果 Bagel CLI",
    no_args_is_help=True,
)
cli_app = typer.Typer(help="External CLI providers (Feishu / …)")
app.add_typer(cli_app, name="cli")
console = Console()


@app.command()
def version() -> None:
    """Print package version."""
    console.print(f"Bagel（贝果） v{__version__}")


@app.command("setup-media")
def setup_media(
    ref: str = typer.Option("main", "--ref", help="Upstream git branch or tag"),
    force: bool = typer.Option(False, "--force", help="Remove broken non-git dir and re-clone"),
    repo: str = typer.Option(
        "https://github.com/NanmiCoder/MediaCrawler.git",
        "--repo",
        help="Upstream git URL",
    ),
) -> None:
    """Clone MediaCrawler into third_party/ (gitignored) and install bagel_entry.py."""
    from bagel.services.media_setup import setup_mediacrawler

    try:
        info = setup_mediacrawler(repo=repo, ref=ref, force=force)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]git failed[/red] {exc.stderr or exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]MediaCrawler {info['action']}[/green] → {info['path']}")
    console.print(f"Entry shim: {info['entry']}")
    console.print(
        "Next: cd third_party/MediaCrawler && create .venv, install deps, "
        "then: .venv/Scripts/python.exe -m playwright install chromium"
    )
    console.print("Set MEDIA_CRAWLER_PATH=./third_party/MediaCrawler in .env")


@app.command()
def doctor() -> None:
    """Run environment health checks (DB / RSSHub / GitHub / LLM / network / Feishu)."""
    from bagel.integrations import feishu_cli
    from bagel.jobs.scheduler import scheduler_status
    from bagel.services.health import format_doctor_report, run_health_checks
    from bagel.storage.database import get_engine, get_session_factory

    session = None
    try:
        engine = get_engine()
        session = get_session_factory(engine)()
    except Exception:  # noqa: BLE001
        session = None
    try:
        report = run_health_checks(session)
        console.print(format_doctor_report(report))
    finally:
        if session is not None:
            session.close()

    st = scheduler_status()
    console.print(
        f"[cyan]Scheduler[/cyan] running={st['running']} enabled={st['enabled']} "
        f"interval={st['interval_minutes']}m jitter={st['jitter_seconds']}s"
    )
    fs = feishu_cli.status()
    console.print(f"[cyan]Feishu[/cyan] {fs.message} ready={fs.ready}")


@app.command()
def dev(
    host: str | None = None,
    port: int | None = None,
    reload: bool = True,
    auto_port: bool = typer.Option(
        False,
        "--auto-port",
        help="If the preferred port cannot bind, try nearby free ports",
    ),
) -> None:
    """Start the FastAPI app for local development."""
    from bagel.cli.ports import resolve_bind_port

    settings = get_settings()
    bind_host = host or settings.app_host
    requested = port if port is not None else settings.app_port
    try:
        bind_port, port_warning = resolve_bind_port(
            bind_host, requested, auto_port=auto_port
        )
    except OSError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    url = f"http://{bind_host}:{bind_port}"
    console.print(f"[bold]Starting Bagel[/bold] on {url}")
    if port_warning:
        console.print(f"[yellow]{port_warning}[/yellow]")
    if settings.auth_required:
        console.print(
            "[dim]Auth on — open the URL and sign in "
            "(default [cyan]liuzemin[/cyan] / [cyan]123456[/cyan]). "
            "Set AUTH_REQUIRED=false in .env to skip login locally.[/dim]"
        )
    else:
        console.print("[dim]Auth off (AUTH_REQUIRED=false).[/dim]")

    # Probe noise is filtered in create_app() so --reload child processes also quiet it.
    reload_excludes = [
        "third_party/MediaCrawler/*",
        "third_party\\MediaCrawler\\*",
        "data/*",
        "data\\*",
        ".venv/*",
        "**/.venv/*",
        "**/__pycache__/*",
        "**/*.pyc",
        ".idea/*",
        ".pytest_cache/*",
    ]
    try:
        uvicorn.run(
            "bagel.main:app",
            host=bind_host,
            port=bind_port,
            reload=reload,
            reload_excludes=reload_excludes if reload else None,
            log_level=settings.log_level.lower(),
        )
    except OSError as exc:
        from bagel.cli.ports import diagnose_bind_failure

        console.print(f"[red]Bind failed[/red] {exc}")
        console.print(diagnose_bind_failure(bind_host, bind_port))
        raise typer.Exit(code=1) from exc


@cli_app.command("status")
def cli_status() -> None:
    """Show external CLI provider status."""
    from bagel.integrations import feishu_cli
    from bagel.services.runtime_config import load_runtime_config

    cfg = load_runtime_config()
    table = Table(title="CLI Providers")
    table.add_column("Provider")
    table.add_column("Enabled")
    table.add_column("Ready")
    table.add_column("Detail")
    fs = feishu_cli.status()
    table.add_row(
        "feishu",
        "yes" if cfg.enable_feishu_cli else "no",
        "yes" if fs.ready else "no",
        fs.message,
    )
    console.print(table)


@cli_app.command("feishu-send")
def feishu_send(
    text: str = typer.Argument(..., help="Message text"),
) -> None:
    """Send a text message via Feishu webhook or lark-cli."""
    from bagel.integrations import feishu_cli

    result = feishu_cli.send_text(text)
    if result.ok:
        console.print("[green]sent[/green]")
        if result.stdout:
            console.print(result.stdout[:400])
    else:
        console.print(f"[red]failed[/red] {result.error or result.stderr or result.returncode}")
        raise typer.Exit(code=1)


@cli_app.command("feishu-digest")
def feishu_digest_cmd(
    kind: str = typer.Argument(
        "yesterday",
        help="yesterday | week | week-this | week-last",
    ),
) -> None:
    """Push yesterday lists or weekly brief snapshots to Feishu."""
    from bagel.integrations import feishu_cli
    from bagel.storage.database import get_engine, get_session_factory

    session = get_session_factory(get_engine())()
    try:
        key = (kind or "yesterday").strip().lower()
        if key in {"yesterday", "day", "y"}:
            result, meta = feishu_cli.push_yesterday_digest(session)
        elif key in {"week", "both", "w"}:
            result, meta = feishu_cli.push_week_briefs_digest(session, which="both")
        elif key in {"week-this", "this"}:
            result, meta = feishu_cli.push_week_briefs_digest(session, which="this")
        elif key in {"week-last", "last"}:
            result, meta = feishu_cli.push_week_briefs_digest(session, which="last")
        else:
            console.print("[red]unknown kind[/red]; use yesterday|week|week-this|week-last")
            raise typer.Exit(code=2)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if result.ok:
        console.print(f"[green]sent[/green] {meta.get('title')} chunks={meta.get('chunks')}")
        console.print(meta.get("counts"))
    else:
        console.print(f"[red]failed[/red] {result.error or result.stderr}")
        raise typer.Exit(code=1)


@cli_app.command("feishu-ask")
def feishu_ask(
    text: str = typer.Argument(..., help='例如：把8月20号到8月21号的体操方向新闻发我'),
    push: bool = typer.Option(False, "--push", help="同时推送到飞书 Webhook"),
) -> None:
    """Parse a Feishu-style command: query DB, crawl if empty, print (optional push)."""
    from bagel.services.feishu_command import handle_command
    from bagel.storage.database import get_engine, get_session_factory

    session = get_session_factory(get_engine())()
    try:
        result = handle_command(session, text)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    console.print(result.text)
    if push:
        from bagel.integrations import feishu_cli

        for chunk in result.chunks[:6]:
            r = feishu_cli.send_text(chunk)
            if not r.ok:
                console.print(f"[red]push failed[/red] {r.error or r.stderr}")
                raise typer.Exit(code=1)
        console.print("[green]pushed[/green]")


if __name__ == "__main__":
    app()
