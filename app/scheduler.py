"""Pipeline orchestrator — wires scraping → summarisation → email.

Can run once (for cron jobs) or on a recurring schedule (APScheduler).
"""

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.email.renderer import DigestRenderer
from app.models.database import get_db, init_db
from app.models.models import Subscriber
from app.scrapers import run_all_scrapers
from app.services.digest import DigestService
from app.services.email import EmailService

logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    """Execute the full digest pipeline once:

    1. Scrape all sources for new content
    2. Summarise unsummarized articles via Gemini
    3. Render the HTML email digest
    4. Send it via Gmail SMTP
    """
    logger.info("═══ Starting daily digest pipeline ═══")
    start = time.time()

    with get_db() as db:
        # Step 1 — Scrape
        logger.info("Step 1/4: Scraping sources…")
        new_articles = run_all_scrapers(db)
        logger.info("  → %d new articles scraped.", new_articles)

        # Step 2 — Summarise
        logger.info("Step 2/4: Summarising with Gemini…")
        digest_svc = DigestService()
        summarised = digest_svc.summarize_pending(db)
        logger.info("  → %d articles summarised.", summarised)

        # Step 3 — Render email
        logger.info("Step 3/4: Rendering email…")
        renderer = DigestRenderer()
        subject, html_body = renderer.render(db)

        # Step 4 — Send email to .env recipients + DB subscribers
        logger.info("Step 4/4: Sending email…")
        email_svc = EmailService()

        # Gather all recipients: .env list + active subscribers from DB
        env_recipients = settings.email_to_list
        db_subscribers = (
            db.query(Subscriber.email)
            .filter(Subscriber.active == True, Subscriber.confirmed == True)
            .all()
        )
        subscriber_emails = [row[0] for row in db_subscribers]

        # Merge and deduplicate (case-insensitive)
        seen = set()
        all_recipients = []
        for email in env_recipients + subscriber_emails:
            key = email.strip().lower()
            if key not in seen:
                seen.add(key)
                all_recipients.append(email.strip())

        logger.info(
            "Recipients: %d from .env, %d subscribers, %d total (deduplicated)",
            len(env_recipients), len(subscriber_emails), len(all_recipients),
        )

        sent = email_svc.send(subject, html_body, recipients=all_recipients) if all_recipients else False

        elapsed = time.time() - start
        if sent:
            logger.info("═══ Pipeline complete in %.1fs — email sent! ═══", elapsed)
        else:
            logger.warning("═══ Pipeline complete in %.1fs — email NOT sent. ═══", elapsed)


def start_scheduler() -> None:
    """Start APScheduler to run the pipeline daily at DIGEST_SCHEDULE_HOUR (IST)."""
    init_db()

    scheduler = BlockingScheduler()
    trigger = CronTrigger(hour=settings.digest_schedule_hour, minute=0, timezone="Asia/Kolkata")

    scheduler.add_job(run_pipeline, trigger, id="daily_digest", name="Daily AI Digest")

    logger.info(
        "Scheduler started — pipeline will run daily at %02d:00 IST.",
        settings.digest_schedule_hour,
    )
    logger.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
