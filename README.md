# DeepFeed

AI news from top YouTube channels and research blogs — summarized by Gemini and delivered to your inbox every morning.

## Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │              DeepFeed System                 │
                         └──────────────────────────────────────────────┘

 ┌────────────┐    RSS    ┌───────────────────────────────────────────────────────────┐
 │  YouTube   │ ────────▶ │                                                           │
 │  Channels  │           │   ┌─────────┐    ┌───────────┐    ┌────────┐   ┌───────┐ │
 └────────────┘           │   │         │    │           │    │        │   │       │ │
                          │   │ Scrape  │──▶ │ Summarize │──▶ │ Render │──▶│ Email │ │
 ┌────────────┐    RSS    │   │         │    │           │    │        │   │       │ │
 │  Research  │ ────────▶ │   │ youtube │    │  Gemini   │    │ Jinja2 │   │ Gmail │ │
 │  Blogs     │           │   │ blog    │    │  2.0      │    │  HTML  │   │ SMTP  │ │
 └────────────┘           │   └─────────┘    └───────────┘    └────────┘   └───┬───┘ │
                          │        │              │                            │     │
                          │        ▼              ▼                            │     │
                          │   ┌──────────────────────────┐                     │     │
                          │   │     PostgreSQL            │                     │     │
                          │   │  ┌────────┐ ┌─────────┐  │                     │     │
                          │   │  │Articles│ │Subscribers│ │                     │     │
                          │   │  └────────┘ └─────────┘  │                     │     │
                          │   └──────────────────────────┘                     │     │
                          │                                                    │     │
                          │   ┌──────────────────────┐        ┌────────────┐   │     │
                          │   │  FastAPI Web Server   │        │ APScheduler│   │     │
                          │   │  :8000                │        │ 8 AM UTC   │───┘     │
                          │   │  ┌────────────────┐   │        └────────────┘         │
                          │   │  │ Landing Page   │   │                               │
                          │   │  │ /api/subscribe │   │                               │
                          │   │  │ /api/invite    │   │                               │
                          │   │  └────────────────┘   │                               │
                          │   └──────────────────────┘                               │
                          └───────────────────────────────────────────────────────────┘
                                                                       │
                                                                       ▼
                                                              ┌────────────────┐
                                                              │  Subscribers'  │
                                                              │    Inboxes     │
                                                              └────────────────┘
```

### Pipeline flow

1. **Scrape** — `app/scrapers/` pulls new content from YouTube channels (RSS + transcripts) and research blogs (RSS + BeautifulSoup) every 24 hours. New articles are stored in PostgreSQL.

2. **Summarize** — `app/services/llm.py` sends each unsummarized article to Google Gemini 2.0 Flash, which returns a concise summary with key takeaways. Handles rate limits gracefully — unsummarized articles stay in the DB and get picked up on the next run.

3. **Render** — `app/email/renderer.py` uses a Jinja2 HTML template to build a clean, styled email digest from the day's summarized articles.

4. **Deliver** — `app/services/email.py` queries all active subscribers from the database, merges with any `.env` recipients, deduplicates, and sends the digest via Gmail SMTP.

### Web layer

The FastAPI server at port 8000 serves the subscription landing page and exposes:
- `POST /api/subscribe` — creates a new subscriber (or reactivates an existing one)
- `POST /api/invite` — creates an inactive subscriber record for a friend
- `GET /api/subscribers/count` — returns the current subscriber count

### Scheduling

APScheduler runs the full pipeline (scrape → summarize → render → email) once daily at 8 AM UTC. The web server and scheduler run as separate processes (separate Docker containers in production).

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.12+ |
| Database | PostgreSQL 17 + SQLAlchemy 2 |
| LLM | Google Gemini (gemini-2.0-flash) |
| Web | FastAPI + Uvicorn |
| Scheduler | APScheduler |
| Email | Gmail SMTP |
| CLI | Click |
| Container | Docker + docker-compose |

## Quick start

```bash
# Clone
git clone https://github.com/AbhishrutKaushik/ai-news-aggregator.git
cd ai-news-aggregator

# Setup
cp .env.example .env          # fill in your keys
uv sync                       # install deps
python main.py init-db         # create tables

# Add sources
python main.py add-source --type youtube --name "Two Minute Papers" --url "https://youtube.com/channel/UCbfYPyITQ-7l4upoX8nvctg"
python main.py add-source --type blog --name "OpenAI Blog" --url "https://openai.com/blog" --feed-url "https://openai.com/blog/rss.xml"

# Run once
python main.py run

# Or start the daily scheduler
python main.py schedule

# Start the web server (subscription page)
python main.py serve
```

## Docker

```bash
cp .env.example .env           # fill in your keys
cd docker
docker compose up --build -d   # starts db + web + scheduler
```

Services:
- **db** — PostgreSQL 16 on port 5432
- **web** — FastAPI landing page + API on port 8000
- **scheduler** — APScheduler running the daily pipeline

## CLI commands

| Command | Description |
|---------|-------------|
| `python main.py run` | Run the full pipeline once |
| `python main.py schedule` | Start the daily scheduler |
| `python main.py serve` | Start the web server |
| `python main.py init-db` | Create database tables |
| `python main.py add-source` | Add a content source |
| `python main.py list-sources` | List all sources |

## Project structure

```
app/
  config/       Settings (Pydantic)
  email/        HTML renderer + template
  models/       SQLAlchemy models (Source, Article, Subscriber)
  scrapers/     YouTube RSS + Blog scraper
  services/     Digest builder, email sender, LLM client
  summarizer/   Gemini summarization
  web/          FastAPI app, routes, static landing page
docker/         Dockerfile + docker-compose.yml
main.py         Click CLI entry point
```

## Environment variables

See [.env.example](.env.example) for all required variables.

## License

MIT
