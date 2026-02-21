"""Blog / RSS feed scraper.

Supports two strategies:
1. RSS feed parsing via feedparser (preferred).
2. HTML fallback via httpx + BeautifulSoup for sites without RSS.
"""

import logging
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Article, ContentType, Source, SourceType

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 30

# Max chars of raw content to store (keeps LLM context manageable)
MAX_CONTENT_CHARS = 5000


# ── RSS Parsing ──────────────────────────────────────────────────────────────


def fetch_rss_feed(feed_url: str) -> list[dict]:
    """Parse an RSS/Atom feed and return a list of article dicts."""
    try:
        resp = httpx.get(feed_url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch RSS feed %s: %s", feed_url, e)
        return []

    feed = feedparser.parse(resp.text)

    if feed.bozo and not feed.entries:
        logger.warning("Failed to parse RSS feed %s: %s", feed_url, feed.bozo_exception)
        return []

    articles: list[dict] = []
    for entry in feed.entries:
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            published_at = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        # Get summary / content
        raw_content = ""
        if hasattr(entry, "content") and entry.content:
            raw_content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            raw_content = entry.get("summary", "")

        # Strip HTML tags from summary content
        if raw_content:
            soup = BeautifulSoup(raw_content, "html.parser")
            raw_content = soup.get_text(separator=" ", strip=True)

        articles.append(
            {
                "title": entry.get("title", "Untitled"),
                "url": entry.get("link", ""),
                "published_at": published_at,
                "raw_content": raw_content[:MAX_CONTENT_CHARS],
                "author": entry.get("author", ""),
            }
        )

    logger.info("Fetched %d articles from RSS %s", len(articles), feed_url)
    return articles


# ── HTML Scraping (fallback) ─────────────────────────────────────────────────


def scrape_blog_page(url: str) -> list[dict]:
    """Scrape a blog index page for article links and metadata.

    This is a generic fallback — works for pages that list articles
    with <a> tags inside <article> or heading elements.
    """
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles: list[dict] = []

    # Strategy: look for <article> tags, or <a> inside headings
    article_elements = soup.find_all("article")
    if not article_elements:
        # Fallback: look for links in h2/h3 tags
        article_elements = soup.find_all(["h2", "h3"])

    for el in article_elements:
        link_tag = el.find("a", href=True) if el.name != "a" else el
        if not link_tag or not link_tag.get("href"):
            continue

        href = link_tag["href"]
        # Make absolute URL if relative
        if href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(url, href)
        elif not href.startswith("http"):
            continue

        title = link_tag.get_text(strip=True) or "Untitled"

        articles.append(
            {
                "title": title,
                "url": href,
                "published_at": None,
                "raw_content": "",
                "author": "",
            }
        )

    logger.info("Scraped %d article links from %s", len(articles), url)
    return articles


def fetch_article_content(url: str) -> str:
    """Fetch a single article page and extract plain text content."""
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch article %s: %s", url, e)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove script/style elements
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    # Try to find main content area
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if main:
        text = main.get_text(separator=" ", strip=True)
    else:
        text = soup.get_text(separator=" ", strip=True)

    return text[:MAX_CONTENT_CHARS]


# ── Main Entry Point ────────────────────────────────────────────────────────


def scrape_blogs(db: Session) -> int:
    """Scrape all active blog/website sources in the DB. Returns count of new articles."""
    sources = (
        db.query(Source)
        .filter(Source.type.in_([SourceType.blog, SourceType.website]), Source.active.is_(True))
        .all()
    )

    if not sources:
        logger.info("No active blog/website sources found.")
        return 0

    # Only consider articles from recent window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.fetch_window_hours)

    new_count = 0
    for source in sources:
        feed_url = source.feed_url or source.url

        # Try RSS first
        if feed_url.endswith((".xml", ".rss", ".atom", "/feed", "/rss")):
            raw_articles = fetch_rss_feed(feed_url)
        else:
            # Try RSS anyway (many URLs serve RSS even without extension)
            raw_articles = fetch_rss_feed(feed_url)
            if not raw_articles:
                # Fall back to HTML scraping
                raw_articles = scrape_blog_page(feed_url)

        for raw in raw_articles:
            if not raw["url"]:
                continue

            # Skip old articles (only process recent ones)
            if raw["published_at"] and raw["published_at"] < cutoff:
                continue

            # Skip if already in DB
            exists = db.query(Article.id).filter(Article.url == raw["url"]).first()
            if exists:
                continue

            # If we don't have content from RSS, fetch the article page
            content = raw["raw_content"]
            if not content and raw["url"]:
                content = fetch_article_content(raw["url"])

            article = Article(
                source_id=source.id,
                title=raw["title"],
                url=raw["url"],
                published_at=raw["published_at"],
                raw_content=content,
                content_type=ContentType.blog_post,
                metadata_json={"author": raw["author"]} if raw["author"] else None,
            )
            db.add(article)
            new_count += 1

        logger.info("Source '%s': processed, total new so far = %d", source.name, new_count)

    db.flush()
    return new_count
