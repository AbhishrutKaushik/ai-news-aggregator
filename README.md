# DeepFeed

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Daily Digest](https://github.com/AbhishrutKaushik/ai-news-aggregator/actions/workflows/daily-digest.yml/badge.svg)](https://github.com/AbhishrutKaushik/ai-news-aggregator/actions/workflows/daily-digest.yml)

AI news from top YouTube channels and research blogs — summarized by Gemini and delivered to your inbox every morning.

## Features

- **Multi-source aggregation** — Scrapes YouTube channels and AI research blogs via RSS
- **AI-powered summaries** — Google Gemini 2.0 Flash generates concise summaries with key takeaways (watch out for free-tier quotas; see troubleshooting below)
- **Beautiful email digests** — Clean, responsive HTML emails delivered via Gmail SMTP. Recipients are added as BCC by default so they don't see each other's addresses.
- **Subscriber management** — Web UI for subscriptions + invite friends feature
- **Automated scheduling** — GitHub Actions runs daily at 8 AM IST (no server required!)
- **Docker support** — One-command deployment with docker-compose

## Pre-configured Sources

### YouTube Channels (12)
| Channel | Focus |
|---------|-------|
| Two Minute Papers | AI research papers explained |
| Google DeepMind | DeepMind research updates |
| Yannic Kilcher | ML paper reviews |
| AI Explained | AI news and analysis |
| Fireship | Tech news, quick explainers |
| Sentdex | Python & ML tutorials |
| ML Street Talk | AI researcher interviews |
| Weights & Biases | MLOps and experiments |
| AI Jason | AI tools and tutorials |
| The AI Epiphany | Deep learning explanations |
| StatQuest | Statistics and ML fundamentals |
| Computerphile | Computer science concepts |

### AI Blogs (12)
| Blog | Publisher |
|------|-----------|
| OpenAI Blog | OpenAI |
| Hugging Face Blog | Hugging Face |
| Google AI Blog | Google |
| Anthropic | Anthropic |
| DeepMind Blog | Google DeepMind |
| Meta AI | Meta |
| MIT AI News | MIT |
| The Gradient | Independent |
| MarkTechPost | Independent |
| Machine Learning Mastery | Jason Brownlee |
| Lilian Weng Blog | OpenAI researcher |
| Karpathy Blog | Andrej Karpathy |

## Architecture

### Troubleshooting

- **Summarization failures**: if Gemini returns `RESOURCE_EXHAUSTED` or 429 errors,
  the most common cause is hitting the free‑tier quota (you'll see logs like
  "Quota exceeded for metric: ... limit: 0").
  - Solution: upgrade your Google Cloud account / enable billing, or switch to a
    paid Gemini plan. Alternatively, reduce the number of articles or switch to
    a smaller model in `app/services/llm.py`.
  - The pipeline will keep unsummarized articles in the DB and automatically
    try again on the next run.



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

**Option 1: GitHub Actions (Recommended — No server required!)**

The repository includes a GitHub Actions workflow that runs daily at 8 AM IST. Just push to GitHub and add your secrets:

1. Go to **Settings → Secrets and variables → Actions**
2. Add these repository secrets:
   - `GEMINI_API_KEY` — Your Google Gemini API key
   - `EMAIL_FROM` — Your Gmail address
   - `EMAIL_TO` — Recipient email(s), comma-separated
   - `EMAIL_PASSWORD` — Gmail App Password (16 characters)

The workflow will automatically scrape, summarize, and email — no laptop or server needed!

**Option 2: Local APScheduler**

APScheduler runs the full pipeline (scrape → summarize → render → email) once daily at 8 AM IST. Requires keeping `python main.py schedule` running.

**Option 3: Docker**

Run the scheduler container which handles everything automatically.

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

### Prerequisites
- Python 3.12+
- PostgreSQL 16+ (or Docker)
- [Google Gemini API Key](https://aistudio.google.com/apikey) (free tier available)
- [Gmail App Password](https://myaccount.google.com/apppasswords) (requires 2FA enabled)

### Local Setup

```bash
# Clone
git clone https://github.com/AbhishrutKaushik/ai-news-aggregator.git
cd ai-news-aggregator

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env       # Then fill in your API keys and credentials

# Initialize database
python main.py init-db

# Add sources (or use defaults in .env)
python main.py add-source --type youtube --name "Two Minute Papers" --url "https://youtube.com/channel/UCbfYPyITQ-7l4upoX8nvctg"
python main.py add-source --type blog --name "OpenAI Blog" --url "https://openai.com/blog" --feed-url "https://openai.com/blog/rss.xml"

# Run once (test)
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
