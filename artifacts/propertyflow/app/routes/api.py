"""JSON API + demo trigger endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import current_user, require_role, require_user
from app.db import get_db
from app.models import Item, ItemStatus, Role, User
from app.services import workflow_service

router = APIRouter()

# Writes through the JSON API and demo triggers require operator+.
WRITE_ROLES = (Role.operator, Role.admin)


class CreateItem(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    sender_name: str | None = None
    sender_email: str | None = None


@router.post("/api/items")
def create_item(payload: CreateItem, user: User = Depends(require_role(*WRITE_ROLES)), db: Session = Depends(get_db)):
    if user.role is Role.owner:
        # Owner can post into any tenant via ?tenant_id=, but for the MVP
        # we just refuse rather than guess.
        raise HTTPException(400, "owner must specify tenant via the admin UI")
    if not user.tenant_id:
        raise HTTPException(400, "user is not attached to a tenant")
    item = workflow_service.ingest_item(
        db,
        tenant_id=user.tenant_id,
        subject=payload.subject,
        body=payload.body,
        sender_name=payload.sender_name,
        sender_email=payload.sender_email,
        actor_user_id=user.id,
    )
    return {"id": item.id, "status": item.status.value, "category": item.category, "ai_mode": item.ai_mode}


# --- Demo scenarios ---------------------------------------------------------
# Posted from the dashboard "Try a scenario" buttons. They run through the
# full pipeline so the user sees real classification + draft generation.

DEMO_SCENARIOS: dict[str, dict[str, str]] = {
    "boiler": {
        "subject": "URGENT — boiler dead at 7 Maple Avenue",
        "body": "Boiler stopped working overnight. No heat, no hot water, baby in the flat — please can someone come out today.",
        "sender_name": "Aisha Khan",
        "sender_email": "aisha@example.com",
    },
    "viewing": {
        "subject": "Viewing request for the 2-bed on Gladstone St",
        "body": "Hi — saw the listing, would love to view the 2-bed on Gladstone Street this week. I'm flexible on time.",
        "sender_name": "Rob Daniels",
        "sender_email": "rob@example.com",
    },
    "landlord": {
        "subject": "Q1 statement and gas safety renewal",
        "body": "Hello — could I get the Q1 statement for my three properties, and confirmation that the gas safety renewal at 14 Park has been booked?",
        "sender_name": "Mrs Holloway",
        "sender_email": "holloway@example.com",
    },
    "chase": {
        "subject": "Chasing — deposit return (3rd request)",
        "body": "This is my third email about my deposit return. Tenancy ended 6 weeks ago. Please can someone get back to me today.",
        "sender_name": "Daniel Brooks",
        "sender_email": "daniel@example.com",
    },
}


@router.post("/demo/{key}")
def trigger_demo(key: str, request: Request, user: User = Depends(require_role(*WRITE_ROLES)), db: Session = Depends(get_db)):
    scenario = DEMO_SCENARIOS.get(key)
    if not scenario:
        raise HTTPException(404, "unknown scenario")
    if not user.tenant_id:
        raise HTTPException(400, "owner cannot post demo items — log in as a tenant user")
    item = workflow_service.ingest_item(
        db,
        tenant_id=user.tenant_id,
        subject=scenario["subject"],
        body=scenario["body"],
        sender_name=scenario.get("sender_name"),
        sender_email=scenario.get("sender_email"),
        actor_user_id=user.id,
    )
    # If posted from a regular form, redirect back to the item.
    if request.headers.get("accept", "").startswith("text/html"):
        return RedirectResponse(f"/items/{item.id}", status_code=303)
    return JSONResponse({"id": item.id, "category": item.category, "ai_mode": item.ai_mode})
