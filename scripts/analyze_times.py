from sqlalchemy import func, select

from bagel.domain.models import IntelItem
from bagel.settings import get_settings
from bagel.storage.database import get_engine, get_session_factory

s = get_settings()
eng = get_engine(s.database_url)
db = get_session_factory(eng)()
total = db.scalar(select(func.count()).select_from(IntelItem))
null_pub = db.scalar(
    select(func.count()).select_from(IntelItem).where(IntelItem.published_at.is_(None))
)
news = db.scalar(select(func.count()).select_from(IntelItem).where(IntelItem.item_type == "NEWS"))
news_null = db.scalar(
    select(func.count())
    .select_from(IntelItem)
    .where(IntelItem.item_type == "NEWS", IntelItem.published_at.is_(None))
)
print("total", total, "null_published", null_pub, "news", news, "news_null_pub", news_null)
rows = db.scalars(
    select(IntelItem)
    .where(IntelItem.item_type == "NEWS", IntelItem.status == "CANDIDATE")
    .order_by(IntelItem.score.desc(), IntelItem.published_at.desc().nullslast())
    .limit(8)
).all()
for r in rows:
    print("---")
    print((r.title or "")[:70])
    print("published", r.published_at, "fetched", r.fetched_at, "score", r.score)
db.close()
