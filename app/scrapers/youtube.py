"""YouTube RSS feed scraper + transcript fetcher.

YouTube exposes public RSS feeds at:
    https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}

Transcripts are fetched via youtube-transcript-api (no API key needed).
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy.orm import Session
from youtube_transcript_api import YouTubeTranscriptApi

from app.config import settings
from app.models.models import Article, ContentType, Source, SourceType

logger = logging.getLogger(__name__)

YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
HTTP_TIMEOUT = 30
MAX_TRANSCRIPT_CHARS = 5000


def extract_video_id(url: str) -> str | None:
    """Extract the video ID from a YouTube URL."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_transcript(video_id: str) -> str:
    """Fetch the transcript for a YouTube video. Returns plain text or empty string."""
    try:
        ytt = YouTubeTranscriptApi()
        transcript_list = ytt.list(video_id)

        # Prefer manually created English, then any English, then first available
        transcript = None
        for t in transcript_list:
            if t.language_code.startswith("en") and not t.is_generated:
                transcript = t
                break
        if transcript is None:
            for t in transcript_list:
                if t.language_code.startswith("en"):
                    transcript = t
                    break
        if transcript is None:
            transcript = next(iter(transcript_list))

        snippets = transcript.fetch()
        full_text = " ".join(snippet.text for snippet in snippets)
        return full_text[:MAX_TRANSCRIPT_CHARS]

    except Exception as e:
        logger.debug("No transcript for video %s: %s", video_id, e)
        return ""


def fetch_youtube_feed(channel_id: str) -> list[dict]:
    """Parse a YouTube channel's RSS feed and return a list of video dicts."""
    url = YOUTUBE_RSS_URL.format(channel_id=channel_id)

    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch YouTube feed for %s: %s", channel_id, e)
        return []

    feed = feedparser.parse(resp.text)

    if feed.bozo and not feed.entries:
        logger.warning("Failed to parse YouTube feed for %s: %s", channel_id, feed.bozo_exception)
        return []

    videos: list[dict] = []
    for entry in feed.entries:
        # Parse published date
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

        # Extract thumbnail from media:group
        thumbnail = None
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            thumbnail = entry.media_thumbnail[0].get("url")

        videos.append(
            {
                "title": entry.get("title", "Untitled"),
                "url": entry.get("link", ""),
                "published_at": published_at,
                "raw_content": entry.get("summary", ""),
                "thumbnail": thumbnail,
                "author": entry.get("author", ""),
            }
        )

    logger.info("Fetched %d videos from channel %s", len(videos), channel_id)
    return videos


def scrape_youtube_channels(db: Session) -> int:
    """Scrape all active YouTube sources in the DB. Returns count of new articles."""
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
        # channel_id is stored in feed_url or extracted from url
        channel_id = source.feed_url or source.url.split("/")[-1]
        videos = fetch_youtube_feed(channel_id)

        for video in videos:
            # Skip old videos
            if video["published_at"] and video["published_at"] < cutoff:
                continue

            # Skip if already in DB
            exists = db.query(Article.id).filter(Article.url == video["url"]).first()
            if exists:
                continue

            # Fetch transcript as primary content (falls back to description)
            video_id = extract_video_id(video["url"])
            transcript = ""
            if video_id:
                transcript = fetch_transcript(video_id)

            raw_content = transcript if transcript else video["raw_content"]
            has_transcript = bool(transcript)

            article = Article(
                source_id=source.id,
                title=video["title"],
                url=video["url"],
                published_at=video["published_at"],
                raw_content=raw_content,
                content_type=ContentType.video,
                metadata_json={
                    "thumbnail": video["thumbnail"],
                    "author": video["author"],
                    "has_transcript": has_transcript,
                    "video_id": video_id,
                },
            )
            db.add(article)
            new_count += 1

        logger.info("Source '%s': %d new videos", source.name, new_count)

    db.flush()
    return new_count
