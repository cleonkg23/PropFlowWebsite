"""Admin panel — tenant-level user list, all items, audit log."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import AuditLog, Item, Role, Tenant, User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin")
def admin_home(request: Request, user: User = Depends(require_role(Role.admin)), db: Session = Depends(get_db)):
    tenant_id = user.tenant_id  # owner without a tenant will see None below
    if user.role is Role.owner and tenant_id is None:
        # Owner viewing /admin without a chosen tenant — fall back to the first one.
        first = db.query(Tenant).order_by(Tenant.id).first()
        tenant_id = first.id if first else None

    users = db.query(User).filter(User.tenant_id == tenant_id).order_by(User.role, User.name).all() if tenant_id else []
    items = (
        db.query(Item).filter(Item.tenant_id == tenant_id).order_by(Item.created_at.desc()).limit(100).all()
        if tenant_id
        else []
    )
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(50)
        .all()
        if tenant_id
        else []
    )
    tenant = db.get(Tenant, tenant_id) if tenant_id else None

    return templates.TemplateResponse(
        request,
        "admin.html",
        {"user": user, "tenant": tenant, "users": users, "items": items, "audit": audit},
    )
