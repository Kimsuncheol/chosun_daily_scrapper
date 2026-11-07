import json
import time
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.models import Article, ScrapeRun, db
from app.scraper import ScrapeError, parse_article

URL = "https://www.chosun.com/english/national-en/2026/11/07/ABCDEFGHIJKLMNOPQRSTUVWXYZ/"
AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture
def collector(monkeypatch, article_html):
    class FakeCollector:
        def __init__(self, *args):
            self.deadline = time.monotonic() + 75

        def discover(self):
            return [URL]

        def article(self, url):
            return parse_article(article_html, url)

        def close(self):
            pass

    monkeypatch.setattr("app.service.Collector", FakeCollector)
    return FakeCollector


def test_collect_list_detail_and_idempotency(client, collector):
    first = client.post("/api/v1/scrape-runs", headers=AUTH)
    assert first.status_code == 201
    assert first.json["inserted"] == 1
    assert first.json["status"] == "succeeded"
    assert client.get(first.headers["Location"], headers=AUTH).json == first.json
    article = client.get("/api/v1/articles").json["items"][0]
    first_seen = article["first_seen_at"]
    collector.article = lambda self, url: dict(
        parse_article(Path("tests/fixtures/article.html").read_text(), url),
        title="Updated headline",
    )
    second = client.post("/api/v1/scrape-runs", headers=AUTH)
    assert second.json["inserted"] == 0
    assert second.json["updated"] == 1
    page = client.get("/api/v1/articles?q=updated&section=National").json
    assert page["total"] == 1
    assert page["items"][0]["first_seen_at"] == first_seen
    assert client.get(f"/api/v1/articles/{article['id']}").json["title"] == "Updated headline"
    assert len(client.get("/api/v1/scrape-runs?limit=1", headers=AUTH).json) == 1
    assert db.session.scalar(select(db.func.count()).select_from(Article)) == 1


@pytest.mark.parametrize("path", ["/api/v1/scrape-runs", "/api/v1/scrape-runs/1"])
def test_admin_requires_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/v1/scrape-runs").status_code == 401


def test_missing_token_disables_administration(app, client):
    app.config["SCRAPE_TOKEN"] = ""
    assert client.post("/api/v1/scrape-runs", headers=AUTH).status_code == 503


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "per_page=101",
        "per_page=no",
        "unknown=x",
        "published_from=2026-11-07",
        "published_from=not-a-date",
        "published_from=2026-11-08T00:00:00Z&published_to=2026-11-07T00:00:00Z",
    ],
)
def test_invalid_query(client, query):
    assert client.get(f"/api/v1/articles?{query}").status_code == 422


def test_dates_pagination_and_missing(client, collector):
    client.post("/api/v1/scrape-runs", headers=AUTH)
    assert (
        client.get(
            "/api/v1/articles?published_from=2026-11-07T01:00:00Z&published_to=2026-11-07T02:00:00Z"
        ).json["total"]
        == 1
    )
    assert client.get("/api/v1/articles?published_to=2026-11-07T01:00:00Z").json["total"] == 0
    assert client.get("/api/v1/articles?page=10").json["items"] == []
    assert client.get("/api/v1/articles/999").status_code == 404
    assert client.get("/api/v1/scrape-runs/999", headers=AUTH).status_code == 404


def test_failure_is_recorded(client, collector):
    def fail(self):
        raise ScrapeError("Publisher returned HTTP 503")

    collector.discover = fail
    response = client.post("/api/v1/scrape-runs", headers=AUTH)
    assert response.status_code == 201
    assert response.json["status"] == "failed"
    assert response.json["error"] == "Publisher returned HTTP 503"
    assert db.session.scalar(select(db.func.count()).select_from(ScrapeRun)) == 1


def test_article_failure_and_deferred(client, collector):
    collector.discover = lambda self: [URL] * 41

    def fail(self, url):
        raise ScrapeError("Bad markup")

    collector.article = fail
    run = client.post("/api/v1/scrape-runs", headers=AUTH).json
    assert run["failed"] == 40
    assert run["deferred"] == 1
    assert run["status"] == "failed"


def test_health_and_documentation(app, client):
    assert client.get("/health").json == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json
    assert spec == json.loads(Path("docs/openapi.json").read_text())
    # Every application method must have a documented successful response.
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/") or rule.rule == "/health":
            path = rule.rule.replace("<int:article_id>", "{article_id}").replace(
                "<int:run_id>", "{run_id}"
            )
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                assert any(
                    code.startswith("2")
                    for code in spec["paths"][path][method.lower()]["responses"]
                )
    assert spec["paths"]["/api/v1/scrape-runs"]["post"]["security"] == [{"BearerAuth": []}]
    db.session.execute(text("DROP TABLE article"))
    db.session.commit()
    assert client.get("/health").status_code == 503


def test_postgres_concurrent_lock(client, collector):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("Requires TEST_DATABASE_URL with disposable PostgreSQL")
    with db.engine.connect() as other:
        transaction = other.begin()
        other.execute(text("SELECT pg_advisory_xact_lock(1729031801)"))
        assert client.post("/api/v1/scrape-runs", headers=AUTH).status_code == 409
        transaction.rollback()
    assert client.post("/api/v1/scrape-runs", headers=AUTH).status_code == 201
