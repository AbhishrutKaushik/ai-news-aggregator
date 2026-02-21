"""Application settings loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — reads from .env automatically."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────
    database_url: str = "postgresql://abhishrutkaushik@localhost:5432/ai_news"

    # ── Google Gemini (free tier) ────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── Email (Gmail SMTP) ───────────────────────────────
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""  # Gmail App Password (16 chars)

    # ── Sources ──────────────────────────────────────────
    youtube_channel_ids: str = ""  # comma-separated channel IDs
    blog_urls: str = ""            # comma-separated RSS / blog URLs

    # ── Personalization / Schedule ───────────────────────
    user_interests: str = "AI, machine learning, large language models"
    digest_schedule_hour: int = 8   # hour of day (UTC)
    fetch_window_hours: int = 24

    # ── Helpers ──────────────────────────────────────────

    @property
    def youtube_channel_id_list(self) -> list[str]:
        """Return YouTube channel IDs as a list."""
        return [cid.strip() for cid in self.youtube_channel_ids.split(",") if cid.strip()]

    @property
    def blog_url_list(self) -> list[str]:
        """Return blog URLs as a list."""
        return [url.strip() for url in self.blog_urls.split(",") if url.strip()]


settings = Settings()
