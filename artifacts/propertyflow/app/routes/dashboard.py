"""Operator dashboard + item detail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import require_role, require_user
from app.db import get_db
from app.models import Item, ItemStatus, Role, Task, TaskStatus, Tenant, User
from app.services import workflow_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Mutating endpoints require at least operator (viewer is read-only).
WRITE_ROLES = (Role.operator, Role.admin)


def _format_updated(dt: datetime | None) -> str:
    if not dt:
        return "just now"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m} min{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = secs // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _tenant_scope(user: User):
    """Filter clause restricting to the user's tenant — owner sees everything."""
    if user.role is Role.owner:
        return None
    return Item.tenant_id == user.tenant_id


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = db.query(Item)
    scope = _tenant_scope(user)
    if scope is not None:
        q = q.filter(scope)
    items = q.order_by(Item.created_at.desc()).limit(200).all()

    # Group by status for the board.
    columns = {s: [] for s in ItemStatus}
    for it in items:
        columns[it.status].append(it)

    my_tasks_q = db.query(Task).filter(Task.assigned_user_id == user.id, Task.status == TaskStatus.open)
    my_tasks = my_tasks_q.order_by(Task.due_at.asc().nullslast()).all()

    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None

    # Freshness + workflow strip + metric counts.
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _ts(dt):
        return dt.replace(tzinfo=timezone.utc) if (dt and dt.tzinfo is None) else dt

    received_today = sum(1 for it in items if _ts(it.created_at) and _ts(it.created_at) >= midnight)
    classified = sum(1 for it in items if it.ai_mode)
    assigned = sum(1 for it in items if it.assigned_user_id)
    reply_ready = sum(1 for it in items if it.draft_reply and it.status != ItemStatus.done)
    tracked = len(columns[ItemStatus.in_progress]) + len(columns[ItemStatus.awaiting_reply])
    active = sum(len(columns[s]) for s in ItemStatus if s != ItemStatus.done)
    action_needed = sum(1 for it in items if it.status == ItemStatus.new or not it.assigned_user_id)
    done_today = sum(
        1 for it in items
        if it.status == ItemStatus.done and _ts(it.updated_at) and _ts(it.updated_at) >= midnight
    )
    processed_today = sum(1 for it in items if _ts(it.created_at) and _ts(it.created_at) >= midnight)

    latest = max((_ts(it.updated_at) or _ts(it.created_at) for it in items), default=None)

    metrics = {
        "received_today": received_today,
        "classified": classified,
        "assigned": assigned,
        "reply_ready": reply_ready,
        "tracked": tracked,
        "active": active,
        "action_needed": action_needed,
        "done_today": done_today,
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "tenant": tenant,
            "columns": columns,
            "my_tasks": my_tasks,
            "statuses": list(ItemStatus),
            "metrics": metrics,
            "updated_label": _format_updated(latest),
            "processed_today": processed_today,
        },
    )


def _load_item_for(user: User, db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    if user.role is not Role.owner and item.tenant_id != user.tenant_id:
        raise HTTPException(404, "item not found")
    return item


@router.get("/items/{item_id}")
def item_detail(item_id: int, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    item = _load_item_for(user, db, item_id)
    # Tenant assignees for the assignment dropdown.
    assignees = (
        db.query(User)
        .filter(User.tenant_id == item.tenant_id, User.role.in_([Role.operator, Role.admin]))
        .order_by(User.name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "item_detail.html",
        {
            "user": user,
            "item": item,
            "assignees": assignees,
            "statuses": list(ItemStatus),
            "valid_next": list(workflow_service.VALID_TRANSITIONS.get(item.status, set())),
        },
    )


@router.post("/items/{item_id}/status")
def post_status(
    item_id: int,
    to_status: str = Form(...),
    user: User = Depends(require_role(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _load_item_for(user, db, item_id)
    try:
        target = ItemStatus(to_status)
    except ValueError:
        raise HTTPException(400, "invalid status")
    try:
        workflow_service.update_status(db, item=item, to_status=target, actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/regenerate-draft")
def post_regen(item_id: int, user: User = Depends(require_role(*WRITE_ROLES)), db: Session = Depends(get_db)):
    item = _load_item_for(user, db, item_id)
    workflow_service.regenerate_draft(db, item=item, actor=user)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/assign")
def post_assign(
    item_id: int,
    assignee_id: str = Form(""),
    user: User = Depends(require_role(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _load_item_for(user, db, item_id)
    new_user = None
    if assignee_id:
        new_user = db.get(User, int(assignee_id))
        if not new_user or (new_user.tenant_id != item.tenant_id):
            raise HTTPException(400, "invalid assignee")
    workflow_service.assign_user(db, item=item, new_user=new_user, actor=user)
    return RedirectResponse(f"/items/{item_id}", status_code=303)
