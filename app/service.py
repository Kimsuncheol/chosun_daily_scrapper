import time

from flask import current_app
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Article, ScrapeRun, db, utcnow
from .scraper import Collector, ScrapeError


class RunInProgress(Exception):
    pass


def collect():
    """Keep the PostgreSQL transaction lock until the complete run commits."""
    if db.engine.dialect.name == "postgresql":
        locked = db.session.execute(text("SELECT pg_try_advisory_xact_lock(1729031801)")).scalar()
        if not locked:
            db.session.rollback()
            raise RunInProgress()
    run = ScrapeRun(discovered=0, processed=0, inserted=0, updated=0, failed=0, deferred=0)
    collector = Collector(current_app.config["SCRAPER_USER_AGENT"])
    db.session.add(run)
    try:
        urls = collector.discover()
        run.discovered = len(urls)
        # Try unseen articles first so a bounded run does not starve new arrivals.
        known = set(db.session.scalars(select(Article.source_id)).all())
        urls.sort(key=lambda u: u.rstrip("/").rsplit("/", 1)[-1] in known)
        for url in urls:
            if run.processed >= 40 or time.monotonic() + 9 >= collector.deadline:
                break
            run.processed += 1
            try:
                values = collector.article(url)
            except ScrapeError:
                current_app.logger.warning("Could not collect article %s", url)
                run.failed += 1
                continue
            now = utcnow()
            values.update(first_seen_at=now, last_seen_at=now)
            insert = pg_insert if db.engine.dialect.name == "postgresql" else sqlite_insert
            statement = insert(Article).values(**values)
            updates = {
                key: getattr(statement.excluded, key)
                for key in values
                if key not in ("source_id", "first_seen_at")
            }
            db.session.execute(
                statement.on_conflict_do_update(index_elements=[Article.source_id], set_=updates)
            )
            if values["source_id"] in known:
                run.updated += 1
            else:
                run.inserted += 1
                known.add(values["source_id"])
        run.deferred = run.discovered - run.processed
        run.status = "partial" if run.failed or run.deferred else "succeeded"
        if run.failed == run.processed and run.processed:
            run.status = "failed"
            run.error = "All article requests failed"
    except ScrapeError as exc:
        run.status = "failed"
        run.error = str(exc)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Scrape transaction failed: %s", type(exc).__name__)
        raise
    finally:
        collector.close()
    run.finished_at = utcnow()
    db.session.commit()
    return run
