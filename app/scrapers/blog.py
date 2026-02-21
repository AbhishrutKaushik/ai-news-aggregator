"""Blog / RSS feed scraper.

Supports two strategies:
1. RSS feed parsing via feedparser (preferred).
2. HTML fallback via httpx + BeautifulSoup for sites without RSS.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Article, ContentType, Source, SourceType

logger = logging.getLogger(__name__)


@dataclass
class BlogArticleItem:
    """Parsed metadata for a single blog article."""

    title: str
    url: str
    published_at: datetime | None = None
    content: str = ""
    author: str = ""


class BlogScraper:
    """Scrapes blog/website sources via RSS feeds with HTML fallback."""

    HTTP_TIMEOUT = 30
    MAX_CONTENT_CHARS = 5_000

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=self.HTTP_TIMEOUT, follow_redirects=True)

    # ── Public API ───────────────────────────────────────────────────────

    def scrape(self, db: Session) -> int:
        """Scrape all active blog/website sources. Returns count of new articles stored."""
        sources = (
            db.query(Source)
            .filter(Source.type.in_([SourceType.blog, SourceType.website]), Source.active.is_(True))
            .all()
        )
        if not sources:
            logger.info("No active blog/website sources found.")
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.fetch_window_hours)
        new_count = 0

        for source in sources:
            feed_url = source.feed_url or source.url
            articles = self._fetch_articles(feed_url)

            for item in articles:
                if not item.url:
                    continue
                if item.published_at and item.published_at < cutoff:
                    continue
                if db.query(Article.id).filter(Article.url == item.url).first():
                    continue

                # If RSS didn't give us body text, fetch the page directly
                if not item.content:
                    item.content = self.fetch_article_content(item.url)

                article = Article(
                    source_id=source.id,
                    title=item.title,
                    url=item.url,
                    published_at=item.published_at,
                    raw_content=item.content,
                    content_type=ContentType.blog_post,
                    metadata_json={"author": item.author} if item.author else None,
                )
                db.add(article)
                new_count += 1

            logger.info("Source '%s': processed, total new so far = %d", source.name, new_count)

        db.flush()
        return new_count

    # ── RSS ──────────────────────────────────────────────────────────────

    def fetch_rss_feed(self, feed_url: str) -> list[BlogArticleItem]:
        """Parse an RSS / Atom feed and return BlogArticleItem objects."""
        try:
            resp = self._http.get(feed_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch RSS feed %s: %s", feed_url, e)
            return []

        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            logger.warning("Failed to parse RSS feed %s: %s", feed_url, feed.bozo_exception)
            return []

        items: list[BlogArticleItem] = []
        for entry in feed.entries:
            published_at = self._parse_date(entry)

            raw_content = ""
            if hasattr(entry, "content") and entry.content:
                raw_content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                raw_content = entry.get("summary", "")

            # Strip HTML from inline content
            if raw_content:
                raw_content = BeautifulSoup(raw_content, "html.parser").get_text(
                    separator=" ", strip=True
                )

            items.append(
                BlogArticleItem(
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", ""),
                    published_at=published_at,
                    content=raw_content[: self.MAX_CONTENT_CHARS],
                    author=entry.get("author", ""),
                )
            )

        logger.info("Fetched %d articles from RSS %s", len(items), feed_url)
        return items

    # ── HTML Scraping (fallback) ─────────────────────────────────────────

    def scrape_blog_page(self, url: str) -> list[BlogArticleItem]:
        """Scrape a blog index page for article links (generic fallback)."""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for <article> tags first, then heading links
        elements = soup.find_all("article") or soup.find_all(["h2", "h3"])

        items: list[BlogArticleItem] = []
        for el in elements:
            link_tag = el.find("a", href=True) if el.name != "a" else el
            if not link_tag or not link_tag.get("href"):
                continue

            href = link_tag["href"]
            if href.startswith("/"):
                href = urljoin(url, href)
            elif not href.startswith("http"):
                continue

            items.append(
                BlogArticleItem(
                    title=link_tag.get_text(strip=True) or "Untitled",
                    url=href,
                )
            )

        logger.info("Scraped %d article links from %s", len(items), url)
        return items

    def fetch_article_content(self, url: str) -> str:
        """Fetch a single article page and extract plain text content."""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch article %s: %s", url, e)
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find("body")
        text = main.get_text(separator=" ", strip=True) if main else soup.get_text(separator=" ", strip=True)
        return text[: self.MAX_CONTENT_CHARS]

    # ── Helpers ──────────────────────────────────────────────────────────

    def _fetch_articles(self, feed_url: str) -> list[BlogArticleItem]:
        """Try RSS first; fall back to HTML scraping if RSS yields nothing."""
        if feed_url.endswith((".xml", ".rss", ".atom", "/feed", "/rss")):
            return self.fetch_rss_feed(feed_url)

        articles = self.fetch_rss_feed(feed_url)
        return articles if articles else self.scrape_blog_page(feed_url)

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        """Extract a timezone-aware datetime from a feedparser entry."""
        for attr in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
        return None
