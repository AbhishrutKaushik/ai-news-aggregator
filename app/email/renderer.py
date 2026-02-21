"""Email renderer — converts Article records into a formatted HTML email.

Uses Jinja2 to render the template with article data.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import Article, ContentType

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent
TEMPLATE_NAME = "template.html"


@dataclass
class DigestItem:
    """Lightweight view-model for the email template."""

    title: str
    url: str
    summary: str
    takeaways: list[str] = field(default_factory=list)
    content_type: str = "news"
    source_name: str = ""
    published_at: str = ""


class DigestRenderer:
    """Queries summarized articles and renders the digest email HTML."""

    def __init__(self) -> None:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )
        self._template = env.get_template(TEMPLATE_NAME)

    def render(self, db: Session) -> tuple[str, str]:
        """Build the HTML digest from recently summarized articles.

        Returns:
            (subject, html_body) — ready to pass to the email sender.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.fetch_window_hours)

        articles = (
            db.query(Article)
            .filter(
                Article.summary.isnot(None),
                Article.created_at >= cutoff,
            )
            .order_by(Article.published_at.desc().nullslast())
            .all()
        )

        items = [self._to_item(a) for a in articles]
        today = datetime.now(timezone.utc).strftime("%B %d, %Y")

        video_count = sum(1 for i in items if i.content_type == "video")
        blog_count = sum(1 for i in items if i.content_type == "blog_post")

        html = self._template.render(
            articles=items,
            date=today,
            video_count=video_count,
            blog_count=blog_count,
            window_hours=settings.fetch_window_hours,
        )

        subject = f"AI News Digest — {today}"
        if not items:
            subject = f"AI News Digest — No new content ({today})"

        logger.info("Rendered digest: %d articles, %d videos, %d blogs", len(items), video_count, blog_count)
        return subject, html

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_item(article: Article) -> DigestItem:
        """Convert an Article ORM object into a template-friendly DigestItem."""
        # Parse bullet-point takeaways back into a list
        takeaways: list[str] = []
        if article.key_takeaways:
            for line in article.key_takeaways.strip().splitlines():
                cleaned = line.lstrip("•-– ").strip()
                if cleaned:
                    takeaways.append(cleaned)

        published = ""
        if article.published_at:
            published = article.published_at.strftime("%b %d, %H:%M UTC")

        source_name = article.source.name if article.source else "Unknown"

        return DigestItem(
            title=article.title,
            url=article.url,
            summary=article.summary or "",
            takeaways=takeaways,
            content_type=article.content_type.value if article.content_type else "news",
            source_name=source_name,
            published_at=published,
        )
