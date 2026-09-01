"""Delete duplicate PAPER rows and realign identity hashes."""
from __future__ import annotations

from bagel.settings import get_settings
from bagel.storage.database import get_session_factory, get_engine
from bagel.storage.repositories import ItemRepository


def main() -> None:
    get_settings.cache_clear()
    get_engine()
    session = get_session_factory()()
    try:
        repo = ItemRepository(session)
        result = repo.dedupe_papers()
        session.commit()
        print("dedupe_result", result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
