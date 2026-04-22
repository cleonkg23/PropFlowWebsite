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
    ItemStatus.new: {ItemStatus.in_progress},
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
    )
    db.add(item)
    db.flush()

    due = datetime.utcnow() + timedelta(hours=SLA_HOURS.get(classification.urgency, 8))
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
