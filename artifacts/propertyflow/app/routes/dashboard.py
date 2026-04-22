"""Operator dashboard + item detail."""
from __future__ import annotations

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

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "tenant": tenant,
            "columns": columns,
            "my_tasks": my_tasks,
            "statuses": list(ItemStatus),
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
