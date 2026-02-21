"""LLM service — wraps Google Gemini for article summarization.

Uses the free-tier gemini-2.0-flash model via the google-genai SDK.
"""

import json
import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# ── Prompt templates ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an AI news analyst. Your job is to read raw content from AI-related
articles and videos and produce a concise, informative summary.

The reader is interested in: {interests}

Guidelines:
- Write in clear, accessible language.
- Highlight what is NEW or SIGNIFICANT.
- Ignore boilerplate, ads, navigation text, and cookie notices.
- If the content is too short or meaningless, say so honestly.
"""

SUMMARIZE_PROMPT = """\
Content type: {content_type}
Title: {title}
Source: {source_name}

--- RAW CONTENT ---
{raw_content}
--- END ---

Respond with ONLY valid JSON (no markdown fences) in this exact format:
{{
  "summary": "A 2-4 sentence summary of the key points.",
  "key_takeaways": [
    "First key takeaway",
    "Second key takeaway",
    "Third key takeaway"
  ]
}}
"""


@dataclass
class SummaryResult:
    """Parsed result from the LLM."""

    summary: str
    key_takeaways: list[str]

    @property
    def takeaways_text(self) -> str:
        """Key takeaways as a bullet-point string (for DB storage)."""
        return "\n".join(f"• {t}" for t in self.key_takeaways)


class GeminiLLM:
    """Thin wrapper around Google Gemini for summarization tasks."""

    # Free tier: 15 RPM for gemini-2.0-flash — we add a small delay
    REQUEST_DELAY_SECONDS = 4.5
    MAX_RETRIES = 3

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in .env")

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        self._system_prompt = SYSTEM_PROMPT.format(interests=settings.user_interests)
        logger.info("Gemini LLM initialised (model=%s)", self._model)

    def summarize(
        self,
        raw_content: str,
        title: str = "",
        content_type: str = "article",
        source_name: str = "",
    ) -> SummaryResult:
        """Send content to Gemini and return a structured summary.

        Retries on transient errors with exponential back-off.
        """
        if not raw_content or not raw_content.strip():
            return SummaryResult(
                summary="No content available to summarize.",
                key_takeaways=[],
            )

        prompt = SUMMARIZE_PROMPT.format(
            content_type=content_type,
            title=title,
            source_name=source_name,
            raw_content=raw_content,
        )

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self._system_prompt,
                        temperature=0.3,
                    ),
                )
                result = self._parse_response(response.text)
                # Respect rate limit
                time.sleep(self.REQUEST_DELAY_SECONDS)
                return result

            except json.JSONDecodeError:
                logger.warning(
                    "Attempt %d: Gemini returned invalid JSON, retrying...",
                    attempt,
                )
                time.sleep(2 * attempt)

            except Exception as e:
                logger.warning(
                    "Attempt %d: Gemini API error: %s", attempt, e
                )
                time.sleep(5 * attempt)

        # All retries exhausted
        logger.error(
            "Failed to summarize '%s' after %d attempts", title, self.MAX_RETRIES
        )
        return SummaryResult(
            summary="Summarization failed after multiple attempts.",
            key_takeaways=[],
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> SummaryResult:
        """Extract JSON from the LLM response text."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        data = json.loads(cleaned)
        return SummaryResult(
            summary=data.get("summary", ""),
            key_takeaways=data.get("key_takeaways", []),
        )
