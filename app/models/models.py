"""SQLAlchemy ORM models — Source and Article."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.models.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class SourceType(str, enum.Enum):
    youtube = "youtube"
    blog = "blog"
    website = "website"


class ContentType(str, enum.Enum):
    video = "video"
    blog_post = "blog_post"
    news = "news"


# ── Helper ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Source ───────────────────────────────────────────────────────────────────


class Source(Base):
    """A content source — YouTube channel, blog, or news website."""

    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name = Column(String(255), nullable=False)
    type = Column(Enum(SourceType), nullable=False)
    url = Column(String(2048), nullable=False)
    feed_url = Column(String(2048), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationship
    articles = relationship("Article", back_populates="source", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Source {self.name!r} ({self.type.value})>"


# ── Article ──────────────────────────────────────────────────────────────────


class Article(Base):
    """An individual piece of content (video, blog post, news article)."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    source_id = Column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(1024), nullable=False)
    url = Column(String(2048), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    raw_content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    key_takeaways = Column(Text, nullable=True)
    content_type = Column(Enum(ContentType), nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationship
    source = relationship("Source", back_populates="articles")

    def __repr__(self) -> str:
        return f"<Article {self.title[:60]!r}>"
