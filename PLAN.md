# AI News Aggregator — Implementation Plan

> A fully automated pipeline that collects AI news from YouTube, blogs, and websites, summarizes it with LLMs, and delivers a personalized daily email digest.

---

## Overview

| Layer | Tech |
|-------|------|
| Language | Python 3.12+ |
| ORM / DB | SQLAlchemy 2.x + PostgreSQL |
| Scraping | `feedparser` (RSS/YouTube), `httpx` + `beautifulsoup4` (blogs) |
| LLM | OpenAI API (GPT-4o) via `openai` SDK |
| Email | `smtplib` + MIME (or SendGrid/Resend SDK) |
| Scheduling | APScheduler (local) / Render Cron Job (prod) |
| Containerization | Docker + docker-compose |
| Deployment | Render |

---

## Phase 1 — Project Setup & Configuration

### Step 1.1: Environment & Dependencies

- Initialize `pyproject.toml` with all dependencies:
  - `sqlalchemy[asyncio]`, `psycopg2-binary` (PostgreSQL driver)
  - `alembic` (DB migrations)
  - `feedparser` (RSS parsing)
  - `httpx`, `beautifulsoup4` (HTTP + HTML parsing)
  - `openai` (LLM summarization)
  - `python-dotenv` (env var management)
  - `apscheduler` (job scheduling)
  - `jinja2` (email templating)
- Generate `requirements.txt` from pyproject for Docker compatibility.
- Create `.env.example` with all required environment variables.

### Step 1.2: Configuration Module — `app/config/`

- **`app/config/__init__.py`** — Export the settings object.
- **`app/config/settings.py`** — Pydantic `BaseSettings` class that reads from `.env`:
  - `DATABASE_URL` — PostgreSQL connection string
  - `OPENAI_API_KEY` — LLM access
  - `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_FROM`, `EMAIL_TO`, `EMAIL_PASSWORD`
  - `YOUTUBE_CHANNEL_IDS` — Comma-separated list of YouTube channel IDs
  - `BLOG_URLS` — Comma-separated list of blog RSS/page URLs
  - `USER_INTERESTS` — Free-text description of user interests for the agent prompt
  - `DIGEST_SCHEDULE_HOUR` — Hour of day (UTC) to run the digest (default: 8)
  - `FETCH_WINDOW_HOURS` — How many hours back to fetch (default: 24)

**Deliverables:** Config loads cleanly, `.env.example` is documented.

---

## Phase 2 — Database Models & Setup

### Step 2.1: Database Connection — `app/models/database.py`

- Create SQLAlchemy `engine` and `SessionLocal` factory from `DATABASE_URL`.
- Provide a `get_db()` context manager for session handling.
- Add `init_db()` function that calls `Base.metadata.create_all(engine)`.

### Step 2.2: Models — `app/models/models.py`

Define two core tables:

```
┌──────────────────────────┐       ┌──────────────────────────────────┐
│         sources          │       │            articles              │
├──────────────────────────┤       ├──────────────────────────────────┤
│ id          (PK, UUID)   │──┐    │ id            (PK, UUID)         │
│ name        (str)        │  │    │ source_id     (FK → sources.id)  │
│ type        (enum)       │  └───>│ title         (str)              │
│   "youtube" | "blog"     │       │ url           (str, unique)      │
│   | "website"            │       │ published_at  (datetime)         │
│ url         (str)        │       │ raw_content   (text, nullable)   │
│ feed_url    (str, null)  │       │ summary       (text, nullable)   │
│ active      (bool)       │       │ key_takeaways (text, nullable)   │
│ created_at  (datetime)   │       │ content_type  (str)              │
│ updated_at  (datetime)   │       │   "video" | "blog_post" | "news"│
└──────────────────────────┘       │ metadata_json (JSON, nullable)   │
                                   │ created_at    (datetime)         │
                                   └──────────────────────────────────┘
```

- `sources.type` — Enum: `youtube`, `blog`, `website`
- `articles.url` — Unique constraint to avoid duplicates.
- `articles.metadata_json` — Flexible field for thumbnails, duration, author, etc.
- Relationship: `Source.articles` ↔ `Article.source`

### Step 2.3: Alembic Migrations (Optional but Recommended)

- `alembic init alembic`
- Configure `alembic/env.py` to use `DATABASE_URL` from settings.
- Generate initial migration: `alembic revision --autogenerate -m "initial"`

**Deliverables:** Running `init_db()` creates both tables in PostgreSQL. Models are importable.

---

## Phase 3 — Scrapers

### Step 3.1: YouTube Scraper — `app/scrapers/youtube.py`

Strategy: Use YouTube RSS feeds (no API key needed).

- YouTube exposes RSS at: `https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}`
- Parse with `feedparser`.
- For each entry, extract:
  - `title`, `link` (URL), `published` (datetime), `summary` (description), `thumbnail`
- Check DB for existing URL to avoid duplicates.
- Insert new articles with `source_id` linked, `content_type = "video"`.

Key functions:
```python
async def fetch_youtube_feed(channel_id: str) -> list[dict]
async def scrape_youtube_channels(db: Session) -> int  # returns count of new articles
```

### Step 3.2: Blog Scraper — `app/scrapers/blog.py`

Strategy: Support both RSS feeds and basic HTML scraping.

- **RSS path** (preferred): Parse feed URL with `feedparser`, extract title/link/date/summary.
- **HTML fallback**: Use `httpx` to GET the blog page, parse with `BeautifulSoup`, extract article links and metadata.
- For each article:
  - Fetch full text content via `httpx` + `BeautifulSoup` (strip HTML tags → plain text).
  - Store `raw_content` (truncated to ~5000 chars for LLM context).
- Deduplicate by URL.

Target blogs (initial):
| Blog | RSS URL |
|------|---------|
| OpenAI Blog | `https://openai.com/blog/rss.xml` (or scrape `/blog`) |
| Anthropic Blog | `https://www.anthropic.com/research` (scrape) |
| Google DeepMind | `https://deepmind.google/blog/rss.xml` |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` |

Key functions:
```python
async def fetch_rss_feed(feed_url: str) -> list[dict]
async def scrape_blog_page(url: str) -> str  # returns plain text
async def scrape_blogs(db: Session) -> int
```

### Step 3.3: Scraper Registry — `app/scrapers/__init__.py`

- Provide a unified `run_all_scrapers(db)` function that:
  1. Loads all active sources from the DB.
  2. Routes each source to the correct scraper by `source.type`.
  3. Returns total count of new articles.

**Deliverables:** Running `run_all_scrapers()` populates the `articles` table with new content.

---

## Phase 4 — LLM Summarization

### Step 4.1: LLM Service — `app/services/llm.py`

- Wrapper around the OpenAI API.
- Core function: `summarize_articles(articles: list[Article], user_interests: str) -> str`
- Builds a prompt with:
  1. **System prompt** (agent-style):
     ```
     You are an AI news curator. The user is interested in: {user_interests}.
     Given the following articles/videos published in the last 24 hours,
     produce a concise daily digest. For each item, provide:
     - A 2-3 sentence summary
     - Key takeaways (bullet points)
     - The original link
     Prioritize items most relevant to the user's interests.
     Group by topic if possible.
     ```
  2. **User message**: Serialized list of articles (title, URL, raw_content/summary).
- Use `gpt-4o` (or configurable model).
- Handle token limits: truncate/chunk articles if total tokens > context window.
- Return structured markdown digest.

Key functions:
```python
async def summarize_articles(articles: list[Article], user_interests: str) -> str
async def generate_digest_content(db: Session) -> str
```

### Step 4.2: Digest Generation — `app/services/digest.py`

- Query articles from the last `FETCH_WINDOW_HOURS`.
- If no new articles → skip (or send a "No new content" notice).
- Call `summarize_articles()` with the fetched articles.
- Optionally, store the digest in a `digests` table (for history).
- Return the digest text (markdown).

**Deliverables:** Given articles in the DB, the system produces a well-structured LLM-generated digest.

---

## Phase 5 — Email Delivery

### Step 5.1: Email Service — `app/services/email.py`

- Use `smtplib` + `email.mime` for sending HTML emails.
- Accepts: subject, body (HTML), recipient.
- Configuration from settings: SMTP host/port/credentials.
- Works with Gmail (App Password), SendGrid, Resend, or any SMTP provider.

Key function:
```python
async def send_digest_email(subject: str, html_body: str) -> bool
```

### Step 5.2: Email Template — `app/email/`

- **`app/email/template.html`** — Jinja2 HTML email template:
  - Clean, mobile-friendly layout.
  - Sections for each article/video:
    - Title (linked)
    - Summary snippet
    - Key takeaways as bullet points
    - Source tag (YouTube / Blog / Website)
  - Header: "AI News Digest — {date}"
  - Footer: "Generated by AI News Aggregator"

- **`app/email/renderer.py`** — Renders the Jinja2 template with digest data:
  ```python
  def render_digest_email(digest_markdown: str, date: str) -> str  # returns HTML
  ```

**Deliverables:** A nicely formatted HTML email arrives in the inbox with the daily digest.

---

## Phase 6 — Scheduler & Main Entry Point

### Step 6.1: Scheduler — `app/scheduler.py`

Orchestrate the full daily pipeline:

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌────────────┐
│  Scrape all  │────>│  Fetch new   │────>│  LLM summarize │────>│ Send email │
│   sources    │     │  articles    │     │  & build digest│     │   digest   │
└─────────────┘     └──────────────┘     └────────────────┘     └────────────┘
```

- `run_daily_pipeline()`:
  1. `run_all_scrapers(db)` — Fetch new content.
  2. `generate_digest_content(db)` — Summarize with LLM.
  3. `render_digest_email(digest)` — Build HTML email.
  4. `send_digest_email(subject, html)` — Deliver.
  5. Log results (count of articles, success/failure).

- For local development: Use `APScheduler` `CronTrigger` to run at `DIGEST_SCHEDULE_HOUR`.
- For production (Render): This function is called once per cron invocation.

### Step 6.2: CLI Entry Point — `main.py`

- Parse CLI arguments:
  - `python main.py run` — Execute the pipeline once (for cron jobs / Render).
  - `python main.py schedule` — Start APScheduler loop (for local/Docker).
  - `python main.py init-db` — Create tables.
  - `python main.py add-source --type youtube --name "..." --url "..."` — Add a source.
- Use `argparse` or `click`.

**Deliverables:** `python main.py run` triggers the full pipeline end-to-end.

---

## Phase 7 — Docker & Deployment

### Step 7.1: Dockerfile — `docker/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "run"]
```

### Step 7.2: Docker Compose — `docker/docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ai_news
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    depends_on:
      - db
    env_file:
      - ../.env
    command: python main.py schedule

volumes:
  pgdata:
```

### Step 7.3: Render Deployment

- Create a **Render Cron Job**:
  - Build command: `pip install -r requirements.txt`
  - Start command: `python main.py run`
  - Schedule: `0 8 * * *` (daily at 8 AM UTC)
- Use **Render PostgreSQL** as a managed database.
- Set all env vars in the Render dashboard.

**Deliverables:** `docker-compose up` runs the full stack locally. Render deploys and runs daily.

---

## Implementation Order (Recommended)

| Order | Phase | What | Est. Time |
|-------|-------|------|-----------|
| 1 | **Phase 1** | Project setup, deps, config module | 1-2 hrs |
| 2 | **Phase 2** | Database models, connection, `init_db` | 1-2 hrs |
| 3 | **Phase 3.1** | YouTube scraper | 1-2 hrs |
| 4 | **Phase 3.2** | Blog scraper | 2-3 hrs |
| 5 | **Phase 3.3** | Scraper registry + test all scrapers | 1 hr |
| 6 | **Phase 4** | LLM summarization + digest generation | 2-3 hrs |
| 7 | **Phase 5** | Email template + sending | 1-2 hrs |
| 8 | **Phase 6** | Scheduler, CLI, end-to-end pipeline | 1-2 hrs |
| 9 | **Phase 7** | Docker, docker-compose, Render deploy | 1-2 hrs |

**Total estimated: ~12-18 hours of focused work.**

---

## File Manifest

After full implementation, the project will contain:

```
ai-news-aggregator/
├── app/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py          # Pydantic settings from .env
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py          # Engine, session, init_db()
│   │   └── models.py            # Source, Article SQLAlchemy models
│   ├── scrapers/
│   │   ├── __init__.py          # run_all_scrapers()
│   │   ├── youtube.py           # YouTube RSS feed scraper
│   │   └── blog.py              # Blog RSS + HTML scraper
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm.py               # OpenAI summarization service
│   │   ├── digest.py            # Digest generation logic
│   │   └── email.py             # SMTP email sender
│   ├── email/
│   │   ├── template.html        # Jinja2 HTML email template
│   │   └── renderer.py          # Template rendering
│   ├── summarizer/              # (merged into services/llm.py)
│   │   └── __init__.py
│   └── scheduler.py             # Daily pipeline orchestrator
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .env.example                 # Environment variable template
├── .gitignore
├── main.py                      # CLI entry point
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Environment Variables (`.env.example`)

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_news

# OpenAI
OPENAI_API_KEY=sk-...

# Email (Gmail example)
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_FROM=your-email@gmail.com
EMAIL_TO=your-email@gmail.com
EMAIL_PASSWORD=your-app-password

# Sources (comma-separated)
YOUTUBE_CHANNEL_IDS=UCbfYPyITQ-7l4upoX8nvctg,UC_x5XG1OV2P6uZZ5FSM9Ttw
BLOG_URLS=https://openai.com/blog,https://www.anthropic.com/research

# Personalization
USER_INTERESTS=Large language models, AI agents, retrieval-augmented generation, open-source AI, AI safety

# Schedule
DIGEST_SCHEDULE_HOUR=8
FETCH_WINDOW_HOURS=24
```

---

## Next Steps

When ready to begin implementation, we'll start with **Phase 1** (config + dependencies) and work through each phase sequentially, testing as we go.
