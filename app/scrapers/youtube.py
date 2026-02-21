"""YouTube scraper — fetches channel feeds via RSS and video transcripts.

YouTube exposes public RSS feeds at:
    https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}

Transcripts are fetched via youtube-transcript-api (no API key needed).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy.orm import Session
from youtube_transcript_api import YouTubeTranscriptApi

from app.config import settings
from app.models.models import Article, ContentType, Source, SourceType

logger = logging.getLogger(__name__)


@dataclass
class VideoItem:
    """Parsed metadata for a single YouTube video."""

    title: str
    url: str
    published_at: datetime | None = None
    description: str = ""
    thumbnail: str | None = None
    author: str = ""
    video_id: str | None = None
    transcript: str = ""

    @property
    def best_content(self) -> str:
        """Transcript if available, otherwise the description."""
        return self.transcript or self.description

    @property
    def has_transcript(self) -> bool:
        return bool(self.transcript)


class YouTubeScraper:
    """Scrapes YouTube channels via RSS feeds and fetches video transcripts."""

    RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    HTTP_TIMEOUT = 30
    MAX_TRANSCRIPT_CHARS = 5_000

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=self.HTTP_TIMEOUT, follow_redirects=True)
        self._ytt = YouTubeTranscriptApi()

    # ── Public API ───────────────────────────────────────────────────────

    def scrape(self, db: Session) -> int:
        """Scrape all active YouTube sources. Returns count of new articles stored."""
        sources = (
            db.query(Source)
            .filter(Source.type == SourceType.youtube, Source.active.is_(True))
            .all()
        )
        if not sources:
            logger.info("No active YouTube sources found.")
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.fetch_window_hours)
        new_count = 0

        for source in sources:
            channel_id = source.feed_url or source.url.split("/")[-1]
            videos = self.fetch_feed(channel_id)

            for video in videos:
                if video.published_at and video.published_at < cutoff:
                    continue
                if db.query(Article.id).filter(Article.url == video.url).first():
                    continue

                # Fetch transcript (best-effort)
                if video.video_id:
                    video.transcript = self.fetch_transcript(video.video_id)

                article = Article(
                    source_id=source.id,
                    title=video.title,
                    url=video.url,
                    published_at=video.published_at,
                    raw_content=video.best_content,
                    content_type=ContentType.video,
                    metadata_json={
                        "thumbnail": video.thumbnail,
                        "author": video.author,
                        "has_transcript": video.has_transcript,
                        "video_id": video.video_id,
                    },
                )
                db.add(article)
                new_count += 1

            logger.info("Source '%s': %d new videos", source.name, new_count)

        db.flush()
        return new_count

    def fetch_feed(self, channel_id: str) -> list[VideoItem]:
        """Parse a channel's RSS feed and return VideoItem objects."""
        url = self.RSS_URL.format(channel_id=channel_id)

        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch YouTube feed for %s: %s", channel_id, e)
            return []

        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            logger.warning("Failed to parse feed for %s: %s", channel_id, feed.bozo_exception)
            return []

        videos: list[VideoItem] = []
        for entry in feed.entries:
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            thumbnail = None
            if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                thumbnail = entry.media_thumbnail[0].get("url")

            video_url = entry.get("link", "")

            videos.append(
                VideoItem(
                    title=entry.get("title", "Untitled"),
                    url=video_url,
                    published_at=published_at,
                    description=entry.get("summary", ""),
                    thumbnail=thumbnail,
                    author=entry.get("author", ""),
                    video_id=self.extract_video_id(video_url),
                )
            )

        logger.info("Fetched %d videos from channel %s", len(videos), channel_id)
        return videos

    def fetch_transcript(self, video_id: str) -> str:
        """Fetch the transcript for a video. Returns plain text or empty string."""
        try:
            transcript_list = self._ytt.list(video_id)

            # Prefer manually-created English → any English → first available
            chosen = None
            for t in transcript_list:
                if t.language_code.startswith("en") and not t.is_generated:
                    chosen = t
                    break
            if chosen is None:
                for t in transcript_list:
                    if t.language_code.startswith("en"):
                        chosen = t
                        break
            if chosen is None:
                chosen = next(iter(transcript_list))

            snippets = chosen.fetch()
            full_text = " ".join(s.text for s in snippets)
            return full_text[: self.MAX_TRANSCRIPT_CHARS]

        except Exception as e:
            logger.debug("No transcript for video %s: %s", video_id, e)
            return ""

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def extract_video_id(url: str) -> str | None:
        """Extract the 11-char video ID from any YouTube URL format."""
        match = re.search(
            r"(?:v=|/v/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url
        )
        return match.group(1) if match else None
