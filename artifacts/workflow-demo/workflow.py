"""Workflow engine — pure functions over raw input.

Layered as the spec requires:
  classify_input  -> {category, urgency}
  determine_workflow -> {owner, next_action, due_in_hours}
  generate_draft_response -> str
  create_task -> persisted task dict

Rules are deliberate and readable; swap in an LLM call later by
replacing the body of classify_input. Nothing else needs to change.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from store import add_item, add_task, get_state, new_id, now_iso, update_item

# --- 1. Classification --------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "maintenance": ("boiler", "leak", "broken", "repair", "heating", "no hot water", "damp", "fault"),
    "viewing": ("viewing", "view the", "second viewing", "appointment", "showing"),
    "tenant_enquiry": ("available", "rent", "deposit", "move in", "available to view", "tenancy"),
    "landlord_admin": ("statement", "invoice", "renewal", "landlord", "remit", "compliance", "gas safety"),
}

URGENT_TOKENS = ("urgent", "asap", "emergency", "no hot water", "leak", "no heat", "no heating")
HIGH_TOKENS = ("today", "tomorrow", "chase", "second time", "still waiting")


def classify_input(message: str, source_type: str | None = None) -> dict[str, str]:
    text = message.lower()

    category = source_type or "tenant_enquiry"
    if not source_type:
        for cat, words in CATEGORY_KEYWORDS.items():
            if any(w in text for w in words):
                category = cat
                break

    if any(t in text for t in URGENT_TOKENS):
        urgency = "urgent"
    elif any(t in text for t in HIGH_TOKENS):
        urgency = "high"
    else:
        urgency = "normal"

    return {"category": category, "urgency": urgency}


# --- 2. Routing ---------------------------------------------------------------

OWNER_BY_CATEGORY: dict[str, str] = {
    "maintenance": "Maintenance team",
    "viewing": "Lettings team",
    "tenant_enquiry": "Lettings team",
    "landlord_admin": "Property manager",
}

NEXT_ACTION_BY_CATEGORY: dict[str, str] = {
    "maintenance": "Triage fault and dispatch contractor",
    "viewing": "Confirm slot and send follow-up",
    "tenant_enquiry": "Reply with availability and next steps",
    "landlord_admin": "Pull figures and reply to landlord",
}

SLA_HOURS: dict[str, int] = {"urgent": 2, "high": 8, "normal": 24}


def determine_workflow(category: str, urgency: str) -> dict[str, Any]:
    return {
        "owner": OWNER_BY_CATEGORY.get(category, "Lettings team"),
        "next_action": NEXT_ACTION_BY_CATEGORY.get(category, "Review and reply"),
        "due_in_hours": SLA_HOURS.get(urgency, 24),
    }


# --- 3. Draft response --------------------------------------------------------

DRAFTS: dict[str, str] = {
    "maintenance": (
        "Hi {name},\n\nThanks for letting us know — sorry you're dealing with this. "
        "I've logged it as {urgency} priority and a contractor will be in touch within "
        "{hours} hours to arrange access.\n\nBest,\n{agent}"
    ),
    "viewing": (
        "Hi {name},\n\nThanks again for viewing {property}. To move forward we'd need "
        "two references and proof of ID — happy to send the link if you'd like to proceed.\n\n"
        "Best,\n{agent}"
    ),
    "tenant_enquiry": (
        "Hi {name},\n\nThanks for getting in touch about {property}. It's still available — "
        "I can offer viewings this week. Does Wed afternoon or Thu morning work?\n\n"
        "Best,\n{agent}"
    ),
    "landlord_admin": (
        "Hi {name},\n\nThanks — I'll pull the latest statement and the outstanding items "
        "and come back to you within {hours} hours.\n\nBest,\n{agent}"
    ),
}


def generate_draft_response(item: dict[str, Any], routing: dict[str, Any]) -> str:
    template = DRAFTS.get(item["category"], DRAFTS["tenant_enquiry"])
    return template.format(
        name=item.get("from_name", "there"),
        property=item.get("property", "the property"),
        urgency=item["urgency"],
        hours=routing["due_in_hours"],
        agent="Property Workflow Co.",
    )


# --- 4. Action layer ----------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_progress"},
    "in_progress": {"awaiting_reply", "done"},
    "awaiting_reply": {"in_progress", "done"},
    "done": set(),
}


def update_status(item_id: str, to_status: str) -> dict[str, Any]:
    """Move an item to a new status; rejects invalid transitions."""
    state = get_state()
    item = next((it for it in state["items"] if it["id"] == item_id), None)
    if item is None:
        raise ValueError(f"unknown item: {item_id}")
    current = item["status"]
    if to_status not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"cannot transition {current} -> {to_status}")
    return update_item(item_id, status=to_status) or item


def create_task(item: dict[str, Any], routing: dict[str, Any]) -> dict[str, Any]:
    due = datetime.utcnow() + timedelta(hours=routing["due_in_hours"])
    task = {
        "id": new_id("tsk"),
        "item_id": item["id"],
        "description": routing["next_action"],
        "assigned_to": routing["owner"],
        "due_date": due.isoformat(timespec="seconds") + "Z",
        "status": "open",
    }
    return add_task(task)


# --- 5. Top-level orchestration ----------------------------------------------

def ingest(payload: dict[str, Any]) -> dict[str, Any]:
    """Single entry point — used by /ingest and the demo scenario triggers."""
    classification = classify_input(
        message=payload.get("message", ""),
        source_type=payload.get("type"),
    )
    item = {
        "id": new_id("itm"),
        "type": classification["category"],
        "message": payload.get("message", ""),
        "from_name": payload.get("from_name", "Unknown sender"),
        "property": payload.get("property"),
        "category": classification["category"],
        "urgency": classification["urgency"],
        "owner": None,
        "status": "new",
        "created_at": now_iso(),
        "draft": None,
        "task_id": None,
    }
    add_item(item)

    routing = determine_workflow(item["category"], item["urgency"])
    draft = generate_draft_response(item, routing)
    task = create_task(item, routing)

    update_item(
        item["id"],
        owner=routing["owner"],
        next_action=routing["next_action"],
        status="in_progress",
        draft=draft,
        task_id=task["id"],
    )

    return {
        "item_id": item["id"],
        "classification": classification,
        "routing": routing,
        "task": task,
        "draft": draft,
    }
