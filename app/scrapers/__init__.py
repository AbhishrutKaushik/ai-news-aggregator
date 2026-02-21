"""Scraper registry — single entry point to run every scraper."""

import logging

from sqlalchemy.orm import Session

from app.scrapers.blog import BlogScraper
from app.scrapers.youtube import YouTubeScraper

logger = logging.getLogger(__name__)


def run_all_scrapers(db: Session) -> int:
    """Run every registered scraper and return the total count of new articles."""
    youtube = YouTubeScraper()
    blog = BlogScraper()

    total = 0
    for scraper in (youtube, blog):
        name = scraper.__class__.__name__
        try:
            count = scraper.scrape(db)
            total += count
            logger.info("%s: %d new articles", name, count)
        except Exception:
            logger.exception("%s failed", name)

    logger.info("── Scraping complete: %d new items total ──", total)
    return total
