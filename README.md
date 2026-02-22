# DeepFeed

AI news from top YouTube channels and research blogs — summarized by Gemini and delivered to your inbox every morning.

## What it does

1. **Scrape** — Pulls new content from YouTube AI channels and research blogs every 24 hours via RSS feeds
2. **Summarize** — Google Gemini reads each article/transcript and extracts key insights
3. **Render** — Builds a clean HTML email digest using Jinja2 templates
4. **Deliver** — Sends the digest to all subscribers via Gmail SMTP at 8 AM UTC daily

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
