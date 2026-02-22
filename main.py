"""AI News Aggregator — CLI entry point.

Usage:
    python main.py run          Run the full pipeline once (scrape → summarise → email)
    python main.py schedule     Start the APScheduler loop (runs daily)
    python main.py init-db      Create database tables
    python main.py add-source   Add a new content source
    python main.py list-sources Show all configured sources
"""

import logging
import sys

import click

from app.config import settings

# ── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai-news")


# ── CLI ──────────────────────────────────────────────────────────────────────


@click.group()
def cli():
    """AI News Aggregator — collect, summarise, and email AI news."""


@cli.command()
def run():
    """Run the full pipeline once (scrape → summarise → email)."""
    from app.scheduler import run_pipeline

    run_pipeline()


@cli.command()
def schedule():
    """Start the APScheduler loop (runs the pipeline daily)."""
    from app.scheduler import start_scheduler

    start_scheduler()


@cli.command("init-db")
def init_db():
    """Create all database tables."""
    from app.models.database import init_db as _init_db

    _init_db()


@cli.command("add-source")
@click.option(
    "--type", "source_type",
    type=click.Choice(["youtube", "blog", "website"], case_sensitive=False),
    required=True,
    help="Type of source.",
)
@click.option("--name", required=True, help="Human-readable name (e.g. 'Two Minute Papers').")
@click.option("--url", required=True, help="Channel/blog URL.")
@click.option("--feed-url", default=None, help="RSS feed URL (optional; auto-detected for YouTube).")
def add_source(source_type: str, name: str, url: str, feed_url: str | None):
    """Add a new content source to the database."""
    from app.models.database import get_db
    from app.models.models import Source, SourceType

    stype = SourceType(source_type.lower())

    # For YouTube, auto-build the feed URL from the channel URL if not provided
    if stype == SourceType.youtube and not feed_url:
        channel_id = url.rstrip("/").split("/")[-1]
        feed_url = channel_id  # stored in feed_url column; scraper uses it as channel_id

    with get_db() as db:
        source = Source(
            name=name,
            type=stype,
            url=url,
            feed_url=feed_url,
            active=True,
        )
        db.add(source)
        db.flush()
        click.echo(f"✔ Added source: {source}")


@cli.command("list-sources")
def list_sources():
    """Show all configured sources."""
    from app.models.database import get_db
    from app.models.models import Source

    with get_db() as db:
        sources = db.query(Source).order_by(Source.type, Source.name).all()
        if not sources:
            click.echo("No sources configured. Use 'add-source' to add one.")
            return

        click.echo(f"\n{'Type':<10} {'Active':<8} {'Name':<30} {'URL'}")
        click.echo("─" * 90)
        for s in sources:
            active = "✔" if s.active else "✗"
            click.echo(f"{s.type.value:<10} {active:<8} {s.name:<30} {s.url}")
        click.echo()


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host.")
@click.option("--port", default=8000, type=int, help="Bind port.")
@click.option("--reload", "do_reload", is_flag=True, help="Enable auto-reload for development.")
def serve(host: str, port: int, do_reload: bool):
    """Start the web server (subscription page + API)."""
    import uvicorn

    click.echo(f"🚀 DeepFeed web server starting at http://{host}:{port}")
    uvicorn.run(
        "app.web:create_app",
        factory=True,
        host=host,
        port=port,
        reload=do_reload,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
