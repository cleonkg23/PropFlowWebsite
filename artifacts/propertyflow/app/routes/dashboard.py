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
from app.models import AuditLog, Item, ItemStatus, Role, Task, TaskStatus, Tenant, User
from app.services import workflow_service

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Mutating endpoints require at least operator (viewer is read-only).
WRITE_ROLES = (Role.operator, Role.admin)


def _is_assigned(user: User, item: Item) -> bool:
    """True if the user is the assignee on the item or on any of its tasks.

    Used to decide whether a contractor can interact with an item — they
    cannot see tickets they aren't on, and they cannot act on tickets they
    aren't on, full stop."""
    if item.assigned_user_id == user.id:
        return True
    return any(t.assigned_user_id == user.id for t in item.tasks)


def _can_act_on_item(user: User, item: Item) -> bool:
    """Permission gate for posting timeline notes and (in future) other
    contractor-allowed actions. Operators+ can always act; contractors only
    if they're the assignee."""
    if user.role in (Role.operator, Role.admin, Role.owner):
        return True
    if user.role is Role.contractor:
        return _is_assigned(user, item)
    return False


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
def dashboard(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    q: str = "",                  # free-text on subject/sender
    status_filter: str = "",      # one of ItemStatus values, or ""
    mine: int = 0,                # 1 → only items assigned to me
    due: str = "",                # "overdue" → only items past their due_at
):
    base = db.query(Item)
    scope = _tenant_scope(user)
    if scope is not None:
        base = base.filter(scope)

    # Filters are additive and persisted as querystring params so they're
    # bookmarkable / shareable inside the team.
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Item.subject.ilike(like), Item.sender_name.ilike(like)))
    if status_filter:
        try:
            base = base.filter(Item.status == ItemStatus(status_filter))
        except ValueError:
            pass
    if mine:
        base = base.filter(Item.assigned_user_id == user.id)
    # Contractors only ever see items where they're the assignee on the item
    # OR on a task. This is a hard filter (not optional like 'mine') because
    # contractors are external users — exposing other tenants' work would be
    # a confidentiality leak even if they couldn't act on it.
    if user.role is Role.contractor:
        contractor_item_ids = {
            row[0] for row in db.query(Task.item_id)
            .filter(Task.assigned_user_id == user.id)
            .all()
        }
        base = base.filter(or_(
            Item.assigned_user_id == user.id,
            Item.id.in_(contractor_item_ids) if contractor_item_ids else Item.id == -1,
        ))
    now_naive = datetime.utcnow()
    if due == "overdue":
        base = base.filter(
            Item.due_at.isnot(None),
            Item.due_at < now_naive,
            Item.status != ItemStatus.done,
        )

    items = base.order_by(Item.created_at.desc()).limit(200).all()
    filters = {"q": q, "status": status_filter, "mine": int(bool(mine)), "due": due}

    # Group by status for the board.
    columns = {s: [] for s in ItemStatus}
    for it in items:
        columns[it.status].append(it)

    # Per-user task state for each visible item. The dashboard shows the
    # *item's* status by default, but that can be misleading for someone
    # who has finished their own task — they see "In progress" and assume
    # they still need to act, when really they're done and waiting on
    # someone else. We surface a "your part is done" / "action needed
    # from you" badge per row to fix that.
    item_ids = [it.id for it in items] or [-1]
    my_task_rows = (
        db.query(Task.item_id, Task.status)
        .filter(Task.assigned_user_id == user.id, Task.item_id.in_(item_ids))
        .all()
    )
    my_state_by_item: dict[int, str] = {}
    for item_id, status in my_task_rows:
        # If they have ANY open task on the item, that wins — they need to
        # act. Otherwise (only done tasks), they're done with their part.
        if status is TaskStatus.open:
            my_state_by_item[item_id] = "open"
        elif my_state_by_item.get(item_id) != "open":
            my_state_by_item[item_id] = "done"

    my_tasks_q = db.query(Task).filter(Task.assigned_user_id == user.id, Task.status == TaskStatus.open)
    my_tasks = my_tasks_q.order_by(Task.due_at.asc().nullslast()).all()

    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None

    # Freshness + workflow strip + metric counts.
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _ts(dt):
        return dt.replace(tzinfo=timezone.utc) if (dt and dt.tzinfo is None) else dt

    reply_ready = sum(1 for it in items if it.draft_reply and it.status != ItemStatus.done)
    active = sum(len(columns[s]) for s in ItemStatus if s != ItemStatus.done)
    done_today = sum(
        1 for it in items
        if it.status == ItemStatus.done and _ts(it.updated_at) and _ts(it.updated_at) >= midnight
    )
    processed_today = sum(1 for it in items if _ts(it.created_at) and _ts(it.created_at) >= midnight)

    # Overdue: open tasks past due
    overdue_q = db.query(Task).filter(Task.status == TaskStatus.open, Task.due_at < now.replace(tzinfo=None))
    if user.role is not Role.owner:
        overdue_q = overdue_q.filter(Task.tenant_id == user.tenant_id)
    overdue = overdue_q.count()

    # Average response: minutes from create -> update for items that have moved past 'new'
    response_samples = [
        (_ts(it.updated_at) - _ts(it.created_at)).total_seconds() / 60.0
        for it in items
        if it.status != ItemStatus.new
        and _ts(it.updated_at) and _ts(it.created_at)
        and _ts(it.updated_at) > _ts(it.created_at)
    ]
    if response_samples:
        avg_min = sum(response_samples) / len(response_samples)
        if avg_min < 60:
            avg_response = f"{int(round(avg_min))}m"
        else:
            avg_response = f"{avg_min/60:.1f}h"
    else:
        avg_response = "—"

    latest = max((_ts(it.updated_at) or _ts(it.created_at) for it in items), default=None)

    metrics = {
        "open": active,
        "overdue": overdue,
        "avg_response": avg_response,
        "reply_ready": reply_ready,
        "done_today": done_today,
        "active": active,
        "action_needed": sum(1 for it in items if it.status == ItemStatus.new or not it.assigned_user_id),
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
            "filters": filters,
            "now_utc": now,
            "my_state_by_item": my_state_by_item,
        },
    )


def _load_item_for(user: User, db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    if user.role is not Role.owner and item.tenant_id != user.tenant_id:
        raise HTTPException(404, "item not found")
    # Contractors can only see tickets they're on. Returning 404 instead of
    # 403 here is deliberate: the existence of an unrelated ticket isn't
    # information they should be able to confirm.
    if user.role is Role.contractor and not _is_assigned(user, item):
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

    # Per-item timeline is just the system audit log filtered by item_id +
    # joined to the actor — same source of truth as the admin/owner pages,
    # so we never have two versions of "what happened" drifting apart.
    timeline_rows = (
        db.query(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(AuditLog.item_id == item.id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    timeline = [{"entry": entry, "actor": actor} for entry, actor in timeline_rows]

    now = datetime.now(timezone.utc)

    # The current user's open task on this item (if any). Drives the
    # "Complete this task" panel for the assignee — including contractors,
    # whose entire interaction with the system is via that one panel.
    my_open_task = next(
        (t for t in item.tasks if t.assigned_user_id == user.id and t.status is TaskStatus.open),
        None,
    )
    open_tasks_count = sum(1 for t in item.tasks if t.status is TaskStatus.open)

    return templates.TemplateResponse(
        request,
        "item_detail.html",
        {
            "user": user,
            "item": item,
            "assignees": assignees,
            "statuses": list(ItemStatus),
            "valid_next": list(workflow_service.VALID_TRANSITIONS.get(item.status, set())),
            "timeline": timeline,
            "now_utc": now,
            "my_open_task": my_open_task,
            "open_tasks_count": open_tasks_count,
            # Used by the template's confirm prompt: "completing this will
            # close the ticket".
            "completing_will_close": my_open_task is not None and open_tasks_count == 1,
            "can_act": _can_act_on_item(user, item),
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


@router.post("/items/{item_id}/draft")
def post_edit_draft(
    item_id: int,
    draft_reply: str = Form(...),
    user: User = Depends(require_role(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _load_item_for(user, db, item_id)
    workflow_service.edit_draft(db, item=item, text=draft_reply, actor=user)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/send")
def post_send(item_id: int, user: User = Depends(require_role(*WRITE_ROLES)), db: Session = Depends(get_db)):
    item = _load_item_for(user, db, item_id)
    try:
        workflow_service.send_reply(db, item=item, actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/acknowledge")
def post_acknowledge(item_id: int, user: User = Depends(require_role(*WRITE_ROLES)), db: Session = Depends(get_db)):
    item = _load_item_for(user, db, item_id)
    try:
        workflow_service.acknowledge(db, item=item, actor=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/complete")
def post_complete(
    item_id: int,
    note: str = Form(""),
    user: User = Depends(require_role(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _load_item_for(user, db, item_id)
    try:
        workflow_service.complete(db, item=item, actor=user, note=note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/note")
def post_note(
    item_id: int,
    note: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Anyone with permission to act on this item can post a timeline note —
    operators+admins always, contractors only when they're the assignee.
    Pure viewers are blocked."""
    item = _load_item_for(user, db, item_id)
    if not _can_act_on_item(user, item):
        raise HTTPException(403, "you can only post notes on items assigned to you")
    try:
        workflow_service.add_note(db, item=item, actor=user, text=note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item_id}#timeline", status_code=303)


@router.post("/tasks/{task_id}/complete")
def post_task_complete(
    task_id: int,
    note: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Per-task completion. The assignee can always close their own task;
    operators+admins+owners can close anyone's. Contractors can ONLY close
    tasks assigned to them — even if they have other tasks on the same item."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    item = _load_item_for(user, db, task.item_id)  # also enforces tenant + visibility

    is_assignee = task.assigned_user_id == user.id
    is_ops = user.role in (Role.operator, Role.admin, Role.owner)
    if not (is_assignee or is_ops):
        raise HTTPException(403, "you can only complete tasks assigned to you")

    try:
        workflow_service.complete_task(db, task=task, actor=user, note=note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/items/{item.id}#timeline", status_code=303)


@router.post("/items/{item_id}/reopen")
def post_reopen(
    item_id: int,
    reason: str = Form(""),
    user: User = Depends(require_role(*WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Reopen a closed item. Operators+ only — contractors can't undo a
    closure, even on items they were on."""
    item = _load_item_for(user, db, item_id)
    try:
        workflow_service.reopen_item(db, item=item, actor=user, reason=reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
