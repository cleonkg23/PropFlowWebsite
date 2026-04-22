"""Workflow engine — orchestrates AI + DB writes.

ONE engine. Different "workflows" are just different rule mappings inside
this module. Every mutation goes through here so the audit log stays
honest and side-effects (task creation, draft generation) stay in one place.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Item,
    ItemStatus,
    Role,
    Task,
    TaskStatus,
    Tenant,
    Urgency,
    User,
)
from app.services.ai_service import ai

log = logging.getLogger("propertyflow.workflow")

# Routing rules ---------------------------------------------------------------
# Maps a category to the *role* that should pick it up. The actual user is
# the first matching active operator/admin in the tenant.
ROUTING: dict[str, list[Role]] = {
    "maintenance": [Role.operator, Role.admin],
    "viewing": [Role.operator, Role.admin],
    "tenant_enquiry": [Role.operator, Role.admin],
    "landlord_admin": [Role.admin, Role.operator],
    "general": [Role.operator, Role.admin],
}

NEXT_ACTION: dict[str, str] = {
    "maintenance": "Triage fault and dispatch contractor",
    "viewing": "Confirm slot and send follow-up",
    "tenant_enquiry": "Reply with availability and next steps",
    "landlord_admin": "Pull figures and reply to landlord",
    "general": "Review and reply",
}

SLA_HOURS: dict[str, int] = {"high": 2, "medium": 8, "low": 24}

VALID_TRANSITIONS: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.new: {ItemStatus.acknowledged, ItemStatus.in_progress},
    ItemStatus.acknowledged: {ItemStatus.in_progress, ItemStatus.awaiting_reply, ItemStatus.done},
    ItemStatus.in_progress: {ItemStatus.awaiting_reply, ItemStatus.done},
    ItemStatus.awaiting_reply: {ItemStatus.in_progress, ItemStatus.done},
    ItemStatus.done: set(),
}


def _audit(db: Session, *, tenant_id: Optional[int], user_id: Optional[int], action: str, item_id: Optional[int] = None, detail: str = "") -> None:
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action=action, item_id=item_id, detail=detail))


def _pick_assignee(db: Session, tenant_id: int, category: str) -> Optional[User]:
    """First user in the tenant whose role matches the routing rule."""
    preferred_roles = ROUTING.get(category, [Role.operator, Role.admin])
    candidates = (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.role.in_(preferred_roles))
        .order_by(User.id)
        .all()
    )
    return candidates[0] if candidates else None


# --- Public API --------------------------------------------------------------


def ingest_item(
    db: Session,
    *,
    tenant_id: int,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    sender_email: Optional[str] = None,
    actor_user_id: Optional[int] = None,
) -> Item:
    """Run the full pipeline: classify → assign → draft → task → persist."""
    classification = ai.classify_item(subject, body)
    tenant = db.get(Tenant, tenant_id)
    agent_name = tenant.name if tenant else "Property Workflow"
    draft = ai.generate_draft(subject, body, classification.category, sender_name, agent_name=agent_name)
    assignee = _pick_assignee(db, tenant_id, classification.category)

    due = datetime.utcnow() + timedelta(hours=SLA_HOURS.get(classification.urgency, 8))
    item = Item(
        tenant_id=tenant_id,
        subject=subject,
        body=body,
        sender_name=sender_name,
        sender_email=sender_email,
        category=classification.category,
        urgency=Urgency(classification.urgency),
        status=ItemStatus.in_progress if assignee else ItemStatus.new,
        assigned_user_id=assignee.id if assignee else None,
        draft_reply=draft.text,
        ai_mode=classification.mode,
        due_at=due,
    )
    db.add(item)
    db.flush()

    db.add(
        Task(
            tenant_id=tenant_id,
            item_id=item.id,
            description=NEXT_ACTION.get(classification.category, "Review and reply"),
            assigned_user_id=assignee.id if assignee else None,
            due_at=due,
            status=TaskStatus.open,
        )
    )
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=actor_user_id,
        action="ingest",
        item_id=item.id,
        detail=f"category={classification.category} urgency={classification.urgency} mode={classification.mode}",
    )
    db.commit()
    db.refresh(item)
    return item


def update_status(db: Session, *, item: Item, to_status: ItemStatus, actor: User) -> Item:
    if to_status not in VALID_TRANSITIONS.get(item.status, set()):
        raise ValueError(f"cannot transition {item.status.value} -> {to_status.value}")
    old = item.status
    item.status = to_status
    if to_status is ItemStatus.done:
        # Close any open tasks for this item.
        for task in item.tasks:
            if task.status is TaskStatus.open:
                task.status = TaskStatus.done
        if item.completed_at is None:
            item.completed_at = datetime.utcnow()
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="status_change",
        item_id=item.id,
        detail=f"{old.value} -> {to_status.value}",
    )
    db.commit()
    db.refresh(item)
    return item


def assign_user(db: Session, *, item: Item, new_user: Optional[User], actor: User) -> Item:
    item.assigned_user_id = new_user.id if new_user else None
    # Mirror onto the open task too, so the dashboard "My tasks" stays in sync.
    for task in item.tasks:
        if task.status is TaskStatus.open:
            task.assigned_user_id = item.assigned_user_id
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="assign",
        item_id=item.id,
        detail=f"-> user_id={item.assigned_user_id}",
    )
    db.commit()
    db.refresh(item)
    return item


def edit_draft(db: Session, *, item: Item, text: str, actor: User) -> Item:
    """Operator-edited draft content."""
    item.draft_reply = (text or "").strip()
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="edit_draft",
        item_id=item.id,
        detail=f"len={len(item.draft_reply)}",
    )
    db.commit()
    db.refresh(item)
    return item


def send_reply(db: Session, *, item: Item, actor: User) -> Item:
    """Mark draft as sent — moves item into 'awaiting reply' from the recipient."""
    if not item.draft_reply:
        raise ValueError("no draft to send")
    target = ItemStatus.awaiting_reply
    if target not in VALID_TRANSITIONS.get(item.status, set()) and item.status is not target:
        raise ValueError(f"cannot send from {item.status.value}")
    old = item.status
    if item.status is not target:
        item.status = target
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="send_reply",
        item_id=item.id,
        detail=f"{old.value} -> {item.status.value}",
    )
    db.commit()
    db.refresh(item)
    return item


def acknowledge(db: Session, *, item: Item, actor: User) -> Item:
    """Move a brand-new item into the 'acknowledged' state — used to record that
    we've sent a holding reply (or otherwise let the sender know we received
    their message) without committing to a substantive next step yet."""
    if item.status is not ItemStatus.new:
        raise ValueError(f"can only acknowledge new items (got {item.status.value})")
    old = item.status
    item.status = ItemStatus.acknowledged
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="acknowledge",
        item_id=item.id,
        detail=f"{old.value} -> {item.status.value}",
    )
    db.commit()
    db.refresh(item)
    return item


def complete(db: Session, *, item: Item, actor: User, note: str = "") -> Item:
    """Close out an item with a captured proof-of-completion note. Distinct
    from a bare status flip to 'done' because we persist the note + timestamp
    and only allow it from the active states."""
    if item.status is ItemStatus.done:
        raise ValueError("item is already done")
    if item.status not in (ItemStatus.in_progress, ItemStatus.awaiting_reply, ItemStatus.acknowledged):
        raise ValueError(f"cannot complete from {item.status.value}")
    old = item.status
    item.status = ItemStatus.done
    item.completed_at = datetime.utcnow()
    item.completion_note = (note or "").strip() or None
    for task in item.tasks:
        if task.status is TaskStatus.open:
            task.status = TaskStatus.done
    detail = f"{old.value} -> done"
    if item.completion_note:
        snippet = item.completion_note[:60] + ("…" if len(item.completion_note) > 60 else "")
        detail += f" — {snippet}"
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="complete",
        item_id=item.id,
        detail=detail,
    )
    db.commit()
    db.refresh(item)
    return item


def add_note(db: Session, *, item: Item, actor: User, text: str) -> Item:
    """Operator note attached to the item timeline. Not a status change —
    just a written observation that should be visible to anyone working
    the item later."""
    text = (text or "").strip()
    if not text:
        raise ValueError("note is empty")
    if len(text) > 1000:
        text = text[:1000]
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="note",
        item_id=item.id,
        detail=text,
    )
    db.commit()
    db.refresh(item)
    return item


def regenerate_draft(db: Session, *, item: Item, actor: User) -> Item:
    tenant = db.get(Tenant, item.tenant_id)
    draft = ai.generate_draft(
        item.subject, item.body, item.category, item.sender_name, agent_name=tenant.name if tenant else "Property Workflow"
    )
    item.draft_reply = draft.text
    item.ai_mode = draft.mode
    _audit(
        db,
        tenant_id=item.tenant_id,
        user_id=actor.id,
        action="regenerate_draft",
        item_id=item.id,
        detail=f"mode={draft.mode}",
    )
    db.commit()
    db.refresh(item)
    return item
