"""Database engine and session factory.

Default backend is file-backed SQLite under `data/`. Postgres uses the same
ORM models; call `alembic upgrade head` for production schema upgrades.
`init_db` is safe for local MVP (create_all + light column patches + seed).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from bagel.settings import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_parent(database_url: str) -> None:
    """Create parent dir for file-backed sqlite URLs like sqlite+pysqlite:///./data/bagel.db."""
    if not database_url.startswith("sqlite") or ":memory:" in database_url:
        return
    # sqlalchemy URL forms: sqlite:///./data/x.db  or sqlite+pysqlite:///./data/x.db
    raw = database_url.split(":///", 1)[-1]
    path = Path(raw)
    if path.parent and str(path.parent) not in {".", ""}:
        path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create (or return process-global) SQLAlchemy engine.

    Passing an explicit ``url`` returns a one-off engine without touching the
    process globals — used heavily by unit tests.
    """
    global _engine, _SessionLocal
    database_url = url or get_settings().resolved_database_url
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

    engine = create_engine(database_url, connect_args=connect_args, **engine_kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    if url is None:
        _engine = engine
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


def init_db(*, seed: bool = True) -> None:
    """Create tables (SQLite-friendly) and optionally seed defaults."""
    from bagel.domain.models import Base
    from bagel.storage.seed import seed_if_empty

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_owner_columns(engine)
    if not seed:
        return
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