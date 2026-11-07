import pytest

from app.scraper import Collector, ScrapeError, canonicalize, discover, parse_article

URL = "https://www.chosun.com/english/national-en/2026/11/07/ABCDEFGHIJKLMNOPQRSTUVWXYZ/"


def test_discovery_deduplicates_and_restricts_urls():
    html = f'<a href="{URL}?utm_source=x">a</a><a href="{URL}#x">b</a>'
    html += '<a href="/english/">section</a><a href="https://evil.com/english/x/2026/11/07/ABCDEFGHIJKLMNOPQRSTUVWXYZ/">bad</a>'
    assert discover(html) == [URL]
    assert canonicalize(URL.replace("https:", "http:")) is None
    assert canonicalize(URL.replace("www.chosun.com", "www.chosun.com@evil.com")) is None


def test_parse_embedded_body(article_html):
    article = parse_article(article_html, URL + "?tracking=true")
    assert article["source_id"] == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert article["authors"] == ["Example Reporter"]
    assert article["body"] == "First paragraph.\n\nSecond paragraph."
    assert article["published_at"].isoformat() == "2026-11-07T01:00:00+00:00"
    assert article["url"] == URL


def test_parse_fallbacks_and_missing_title():
    html = '<meta property="og:title" content="Fallback"><meta property="article:author" content="One, Two"><meta property="article:published_time" content="bad"><div class="article-body"><p>Text</p></div>'
    article = parse_article(html, URL)
    assert article["title"] == "Fallback"
    assert article["authors"] == ["One", "Two"]
    assert article["body"] == "Text"
    assert article["published_at"] is None
    with pytest.raises(ScrapeError):
        parse_article("<html></html>", URL)


def test_robots_disallow_prevents_article_request(monkeypatch):
    collector = Collector("ChosunDailyScraper/1.0")
    from urllib.robotparser import RobotFileParser

    collector.robots = RobotFileParser()
    collector.robots.parse(["User-agent: *", "Disallow: /english/"])
    monkeypatch.setattr(
        collector.session, "get", lambda *a, **k: pytest.fail("Must not request forbidden URL")
    )
    with pytest.raises(ScrapeError, match="disallowed"):
        collector.article(URL)
    collector.close()


def test_deadline_prevents_request():
    collector = Collector("test", budget=0)
    with pytest.raises(ScrapeError, match="budget"):
        collector.fetch(URL, check_robots=False)
    collector.close()
