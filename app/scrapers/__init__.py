"""Scraper registry — unified entry point for all scrapers."""

import logging

from sqlalchemy.orm import Session

from app.scrapers.blog import scrape_blogs
from app.scrapers.youtube import scrape_youtube_channels

logger = logging.getLogger(__name__)


def run_all_scrapers(db: Session) -> int:
    """Run every scraper and return total count of new articles inserted."""
    total = 0

    logger.info("── Running YouTube scraper ──")
    yt_count = scrape_youtube_channels(db)
    logger.info("YouTube: %d new videos", yt_count)
    total += yt_count

    logger.info("── Running Blog scraper ──")
    blog_count = scrape_blogs(db)
    logger.info("Blogs: %d new articles", blog_count)
    total += blog_count

    logger.info("── Scraping complete: %d new items total ──", total)
    return total
