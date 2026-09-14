"""Database engine and session factory.

Default backend is file-backed SQLite under `data/`. Postgres uses the same
ORM models; call `alembic upgrade head` for production schema upgrades.
`init_db` is safe for local MVP (create_all + light column patches + seed).
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bagel.settings import DEFAULT_SQLITE_URL, get_settings

logger = logging.getLogger(__name__)

# Keep local boot snappy when Postgres is misconfigured / unreachable.
_PG_CONNECT_TIMEOUT_SEC = 3

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_active_database_url: str | None = None


def _ensure_sqlite_parent(database_url: str) -> None:
    """Create parent dir for file-backed sqlite URLs like sqlite+pysqlite:///./data/bagel.db."""
    if not database_url.startswith("sqlite") or ":memory:" in database_url:
        return
    # sqlalchemy URL forms: sqlite:///./data/x.db  or sqlite+pysqlite:///./data/x.db
    raw = database_url.split(":///", 1)[-1]
    path = Path(raw)
    if path.parent and str(path.parent) not in {".", ""}:
        path.parent.mkdir(parents=True, exist_ok=True)


def reset_engine() -> None:
    """Dispose the process-global engine (used when falling back to SQLite)."""
    global _engine, _SessionLocal, _active_database_url
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:  # noqa: BLE001
            pass
    _engine = None
    _SessionLocal = None
    _active_database_url = None


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create (or return process-global) SQLAlchemy engine.

    Passing an explicit ``url`` returns a one-off engine without touching the
    process globals — used heavily by unit tests.
    """
    global _engine, _SessionLocal, _active_database_url
    database_url = url or _active_database_url or get_settings().resolved_database_url
    if url is None and _engine is not None and _active_database_url == database_url:
        return _engine

    _ensure_sqlite_parent(database_url)
    connect_args: dict = {}
    engine_kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # In-memory SQLite needs a single shared connection or schema vanishes.
        if ":memory:" in database_url:
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["pool_pre_ping"] = False
    elif database_url.startswith("postgresql"):
        # psycopg / libpq: fail fast instead of hanging app startup (~minutes).
        connect_args["connect_timeout"] = _PG_CONNECT_TIMEOUT_SEC
        engine_kwargs["pool_timeout"] = float(_PG_CONNECT_TIMEOUT_SEC)
        engine_kwargs["pool_recycle"] = 300

    engine = create_engine(database_url, connect_args=connect_args, **engine_kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    if url is None:
        if _engine is not None and _engine is not engine:
            try:
                _engine.dispose()
            except Exception:  # noqa: BLE001
                pass
        _engine = engine
        _active_database_url = database_url
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    global _SessionLocal
    if engine is not None:
        return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Generator[Session, None, None]:
    SessionLocal = factory or get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _is_db_unreachable(exc: BaseException) -> bool:
    text_exc = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "connectiontimeout",
        "connection refused",
        "could not connect",
        "operationalerror",
        "timeout expired",
        "server closed the connection",
        "connection reset",
        "name or service not known",
        "nodename nor servname",
        "temporarily unavailable",
    )
    return any(m in text_exc for m in markers)


def probe_db(engine: Engine | None = None) -> None:
    """Open one connection and run ``SELECT 1`` (raises on failure)."""
    eng = engine or get_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))


def init_db(*, seed: bool = True) -> None:
    """Create missing tables (idempotent) and optionally seed defaults."""
    ensure_schema()
    if not seed:
        return
    from bagel.storage.seed import seed_if_empty

    factory = get_session_factory()
    session = factory()
    try:
        seed_if_empty(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db_resilient(*, seed: bool = True, fallback_sqlite: bool | None = None) -> dict[str, str]:
    """Init DB; on unreachable Postgres fall back to local SQLite so the UI can boot.

    Returns ``{"backend": "sqlite"|"postgresql", "url": "...", "fallback": "0"|"1"}``.
    """
    global _active_database_url

    settings = get_settings()
    if fallback_sqlite is None:
        # Local / bagel dev: prefer a working site over a hung Postgres wait.
        fallback_sqlite = bool(settings.is_dev) or settings.app_env.lower() in {
            "test",
            "",
        }

    primary = settings.resolved_database_url
    try:
        reset_engine()
        get_engine(url=None)
        probe_db()
        init_db(seed=seed)
        return {
            "backend": "sqlite" if primary.startswith("sqlite") else "postgresql",
            "url": primary,
            "fallback": "0",
        }
    except Exception as exc:  # noqa: BLE001
        if (
            not fallback_sqlite
            or primary.startswith("sqlite")
            or not _is_db_unreachable(exc)
        ):
            raise
        logger.warning(
            "db.unreachable primary=%s err=%s — falling back to SQLite %s",
            primary.split("@")[-1] if "@" in primary else primary[:80],
            exc,
            DEFAULT_SQLITE_URL,
        )
        reset_engine()
        _active_database_url = DEFAULT_SQLITE_URL
        get_engine()
        init_db(seed=seed)
        return {
            "backend": "sqlite",
            "url": DEFAULT_SQLITE_URL,
            "fallback": "1",
            "error": str(exc)[:240],
        }


def ensure_schema() -> None:
    """Create any missing ORM tables (checkfirst) and apply light column patches.

    Used by local SQLite boot and as a Postgres safety net after Alembic so
    redeploys do not fail when a table was never migrated or was only created
    via ``create_all`` historically (e.g. ``app_user``).
    """
    from bagel.domain.models import Base

    engine = get_engine()
    # checkfirst=True (default): CREATE only when the table is absent.
    Base.metadata.create_all(bind=engine)
    _ensure_owner_columns(engine)

def _ensure_owner_columns(engine: Engine) -> None:
    """Best-effort ADD COLUMN for upgrades on existing DBs."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    alterations: list[tuple[str, str]] = [
        ("app_user", None),  # created by create_all
        ("intel_item", "owner_id"),
        ("intel_source", "owner_id"),
        ("intel_keyword_rule", "owner_id"),
        ("intel_github_query", "owner_id"),
        ("intel_monthly_brief", "owner_id"),
        ("intel_search_event", "owner_id"),
    ]
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for table, column in alterations:
            if column is None:
                continue
            if table not in insp.get_table_names():
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            if dialect == "sqlite":
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} CHAR(36)"))
            else:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} UUID"))
        # Keyword rule scopes (CSV of KeywordScope values).
        if "intel_keyword_rule" in insp.get_table_names():
            cols = {c["name"] for c in insp.get_columns("intel_keyword_rule")}
            if "scopes" not in cols:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            "ALTER TABLE intel_keyword_rule "
                            "ADD COLUMN scopes VARCHAR(255) NOT NULL DEFAULT ''"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE intel_keyword_rule "
                            "ADD COLUMN scopes VARCHAR(255) NOT NULL DEFAULT ''"
                        )
                    )
        # Widen period key so weekly briefs (YYYY-Www) fit.
        if "intel_monthly_brief" in insp.get_table_names():
            if dialect == "postgresql":
                conn.execute(
                    text(
                        "ALTER TABLE intel_monthly_brief "
                        "ALTER COLUMN year_month TYPE VARCHAR(16)"
                    )
                )
            # SQLite ignores VARCHAR length; no-op.