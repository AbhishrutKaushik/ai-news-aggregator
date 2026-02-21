"""Digest service — summarizes unsummarized articles via the LLM.

This is the orchestrator: it queries the DB for articles that have
raw_content but no summary yet, sends each to Gemini, and writes
the summary + key_takeaways back to the article row.
"""

import logging

from sqlalchemy.orm import Session

from app.models.models import Article
from app.services.llm import GeminiLLM

logger = logging.getLogger(__name__)


class DigestService:
    """Finds unsummarized articles and fills in their summaries."""

    def __init__(self) -> None:
        self._llm = GeminiLLM()

    def summarize_pending(self, db: Session) -> int:
        """Summarize every article that has raw_content but no summary.

        Returns the number of articles successfully summarized.
        """
        pending = (
            db.query(Article)
            .filter(
                Article.raw_content.isnot(None),
                Article.raw_content != "",
                Article.summary.is_(None),
            )
            .order_by(Article.created_at.asc())
            .all()
        )

        if not pending:
            logger.info("No unsummarized articles found.")
            return 0

        logger.info("Found %d articles to summarize.", len(pending))
        done = 0

        for article in pending:
            source_name = article.source.name if article.source else "Unknown"
            content_type = article.content_type.value if article.content_type else "article"

            logger.info(
                "Summarizing [%s] %s …",
                content_type,
                article.title[:80],
            )

            result = self._llm.summarize(
                raw_content=article.raw_content,
                title=article.title,
                content_type=content_type,
                source_name=source_name,
            )

            article.summary = result.summary
            article.key_takeaways = result.takeaways_text
            db.flush()
            done += 1

            logger.info(
                "  ✓ Summary (%d chars), %d takeaways",
                len(result.summary),
                len(result.key_takeaways),
            )

        logger.info("Summarization complete: %d / %d articles", done, len(pending))
        return done
