"""System-owner panel — cross-tenant view + AI health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import AuditLog, Item, ItemStatus, Role, Tenant, User
from app.services.ai_service import ai

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/owner")
def owner_home(request: Request, user: User = Depends(require_role(Role.owner)), db: Session = Depends(get_db)):
    tenants = db.query(Tenant).order_by(Tenant.name).all()
    rows = []
    for t in tenants:
        item_count = db.query(func.count(Item.id)).filter(Item.tenant_id == t.id).scalar() or 0
        open_count = (
            db.query(func.count(Item.id))
            .filter(Item.tenant_id == t.id, Item.status != ItemStatus.done)
            .scalar()
            or 0
        )
        user_count = db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar() or 0
        rows.append({"tenant": t, "items": item_count, "open": open_count, "users": user_count})

    audit = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()

    return templates.TemplateResponse(
        request,
        "owner.html",
        {"user": user, "rows": rows, "audit": audit, "ai_status": ai.status()},
    )
