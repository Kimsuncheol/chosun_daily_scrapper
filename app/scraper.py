"""Bounded, sequential collection; never execute publisher JavaScript."""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

HOME = "https://www.chosun.com/english/"
ARTICLE_PATH = re.compile(r"^/english/[a-zA-Z0-9_-]+/\d{4}/\d{2}/\d{2}/([A-Z0-9]{26})/?$")


class ScrapeError(Exception):
    pass


def canonicalize(url):
    parsed = urlsplit(urljoin(HOME, url))
    if parsed.scheme != "https" or parsed.netloc != "www.chosun.com":
        return None
    if not ARTICLE_PATH.fullmatch(parsed.path):
        return None
    return f"https://www.chosun.com{parsed.path.rstrip('/')}/"


def discover(html):
    soup = BeautifulSoup(html, "html.parser")
    return list(
        dict.fromkeys(url for a in soup.select("a[href]") if (url := canonicalize(a["href"])))
    )


def parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        return None


def parse_article(html, url):
    soup = BeautifulSoup(html, "html.parser")
    metadata = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = value if isinstance(value, list) else [value]
        for node in list(nodes):
            if isinstance(node, dict):
                nodes.extend(node.get("@graph", []))
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") in ("NewsArticle", "Article"):
                metadata = node
                break
        if metadata:
            break

    def meta(name):
        node = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
        return node.get("content") if node else None

    canonical = soup.select_one('link[rel="canonical"]')
    canonical = canonicalize(canonical.get("href", "")) if canonical else None
    url = canonicalize(url)
    if not url:
        raise ScrapeError("Invalid article URL")
    source_id = ARTICLE_PATH.fullmatch(urlsplit(url).path).group(1)
    if canonical and ARTICLE_PATH.fullmatch(urlsplit(canonical).path).group(1) == source_id:
        url = canonical
    title = metadata.get("headline") or meta("og:title")
    if not isinstance(title, str) or not title.strip():
        raise ScrapeError("Article has no title")
    authors = metadata.get("author", [])
    authors = authors if isinstance(authors, list) else [authors]
    authors = [a.get("name") if isinstance(a, dict) else a for a in authors]
    authors = [a for a in authors if isinstance(a, str) and a.strip()]
    if not authors and meta("article:author"):
        authors = [a.strip() for a in meta("article:author").split(",")]
    body = metadata.get("articleBody")
    # Arc embeds content as JSON even when the visible body is rendered client-side.
    for script in soup.select("script"):
        text = script.get_text()
        marker = "Fusion.globalContent="
        if marker not in text:
            continue
        try:
            content, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1].lstrip())
            paragraphs = [
                BeautifulSoup(e["content"], "html.parser").get_text(" ", strip=True)
                for e in content.get("content_elements", [])
                if e.get("type") == "text" and isinstance(e.get("content"), str)
            ]
            body = "\n\n".join(paragraphs) or body
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
        break
    if not body:
        paragraphs = soup.select('[itemprop="articleBody"] p, .article-body p')
        body = "\n\n".join(p.get_text(" ", strip=True) for p in paragraphs) or None
    return {
        "source_id": source_id,
        "url": url,
        "title": title.strip(),
        "description": metadata.get("description") or meta("og:description"),
        "body": body,
        "authors": authors,
        "section": metadata.get("articleSection") or meta("article:section"),
        "published_at": parse_date(metadata.get("datePublished") or meta("article:published_time")),
        "modified_at": parse_date(metadata.get("dateModified")),
    }


class Collector:
    def __init__(self, user_agent, budget=75):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.deadline = time.monotonic() + budget
        self.robots = None
        self.last_request = 0

    def close(self):
        self.session.close()

    def fetch(self, url, check_robots=True):
        if check_robots and (not self.robots or not self.robots.can_fetch(self.user_agent, url)):
            raise ScrapeError("URL disallowed by robots.txt")
        interval = max(0.5, (self.robots.crawl_delay(self.user_agent) or 0) if self.robots else 0)
        delay = max(0, interval - (time.monotonic() - self.last_request))
        if time.monotonic() + delay + 1 >= self.deadline:
            raise ScrapeError("Scrape time budget exhausted")
        time.sleep(delay)
        self.last_request = time.monotonic()
        # Reject redirects so publisher links cannot redirect to arbitrary hosts.
        try:
            with self.session.get(
                url, timeout=(3, 5), allow_redirects=False, stream=True
            ) as response:
                if response.status_code != 200:
                    raise ScrapeError(f"Publisher returned HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 5_000_000 or time.monotonic() >= self.deadline:
                        raise ScrapeError("Publisher response exceeded collection limits")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except requests.RequestException as exc:
            raise ScrapeError("Publisher request failed") from exc

    def discover(self):
        text = self.fetch("https://www.chosun.com/robots.txt", check_robots=False)
        self.robots = RobotFileParser()
        self.robots.parse(text.splitlines())
        urls = discover(self.fetch(HOME))
        if not urls:
            raise ScrapeError("No article links found; publisher markup may have changed")
        return urls

    def article(self, url):
        return parse_article(self.fetch(url), url)
