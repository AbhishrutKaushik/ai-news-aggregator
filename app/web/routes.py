"""API routes — serve landing page, handle subscriptions & invites."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from app.models.database import get_db
from app.models.models import Subscriber

logger = logging.getLogger("ai-news.web")

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ── Request / Response schemas ────────────────────────────────────────────


class SubscribeRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    interests: list[str]


class InviteRequest(BaseModel):
    email: EmailStr


class MessageResponse(BaseModel):
    message: str


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def landing_page():
    """Serve the subscription landing page."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(), status_code=200)


@router.post("/api/subscribe", response_model=MessageResponse)
async def subscribe(req: SubscribeRequest):
    """Register a new subscriber."""
    with get_db() as db:
        # Check if already subscribed
        existing = db.query(Subscriber).filter(Subscriber.email == req.email).first()
        if existing:
            if existing.active:
                raise HTTPException(status_code=409, detail="You're already subscribed! 🎉")
            # Re-activate
            existing.active = True
            existing.interests = ", ".join(req.interests) if req.interests else existing.interests
            if req.name:
                existing.name = req.name
            logger.info("Re-activated subscriber: %s", req.email)
            return MessageResponse(message="Welcome back! Your subscription is re-activated. 🎉")

        subscriber = Subscriber(
            email=req.email,
            name=req.name,
            interests=", ".join(req.interests),
            active=True,
            confirmed=True,
            unsubscribe_token=uuid.uuid4().hex,
        )
        db.add(subscriber)
        logger.info("New subscriber: %s (interests: %s)", req.email, req.interests)

    return MessageResponse(message="Welcome to DeepFeed! You'll get your first digest soon. 🎉")


@router.post("/api/invite", response_model=MessageResponse)
async def invite(req: InviteRequest):
    """
    Send an invite to a friend.  For now we create a pre-registered (inactive)
    subscriber record so the invite is tracked.  A real email invite can be
    wired up later via the existing EmailService.
    """
    with get_db() as db:
        existing = db.query(Subscriber).filter(Subscriber.email == req.email).first()
        if existing:
            return MessageResponse(message="Your friend already knows about DeepFeed! 🚀")

        invited = Subscriber(
            email=req.email,
            name=None,
            interests="AI, machine learning, large language models",
            active=False,       # invite only — not yet confirmed
            confirmed=False,
            unsubscribe_token=uuid.uuid4().hex,
        )
        db.add(invited)
        logger.info("Invite sent to: %s", req.email)

    return MessageResponse(message="Invite recorded! We'll let them know. 🚀")


@router.get("/api/subscribers/count")
async def subscriber_count():
    """Simple public stat — total active subscribers."""
    with get_db() as db:
        count = db.query(Subscriber).filter(Subscriber.active == True).count()
    return {"count": count}
