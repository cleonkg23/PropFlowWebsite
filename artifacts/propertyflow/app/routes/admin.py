"""Admin panel — client (tenant)-level user management, items, audit log."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import AuditLog, Item, Role, Tenant, User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Roles an admin is allowed to assign to other users in their own client.
_ADMIN_ASSIGNABLE = {Role.viewer, Role.operator, Role.admin}


def _audit(db: Session, *, tenant_id, user_id, action: str, detail: str = "") -> None:
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action=action, detail=detail))


def _flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session["flash"] = msg
    request.session["flash_kind"] = kind


def _resolve_tenant_id(user: User, db: Session) -> int | None:
    """Owner viewing /admin without a tenant falls back to the first one."""
    if user.tenant_id:
        return user.tenant_id
    if user.role is Role.owner:
        first = db.query(Tenant).order_by(Tenant.id).first()
        return first.id if first else None
    return None


@router.get("/admin")
def admin_home(request: Request, user: User = Depends(require_role(Role.admin)), db: Session = Depends(get_db)):
    tenant_id = _resolve_tenant_id(user, db)

    users = (
        db.query(User).filter(User.tenant_id == tenant_id).order_by(User.role, User.name).all()
        if tenant_id else []
    )
    items = (
        db.query(Item).filter(Item.tenant_id == tenant_id).order_by(Item.created_at.desc()).limit(100).all()
        if tenant_id else []
    )
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc())
        .limit(50)
        .all()
        if tenant_id else []
    )
    tenant = db.get(Tenant, tenant_id) if tenant_id else None

    flash = request.session.pop("flash", None)
    flash_kind = request.session.pop("flash_kind", "ok")

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "tenant": tenant,
            "users": users,
            "items": items,
            "audit": audit,
            "assignable_roles": [Role.viewer, Role.operator, Role.admin],
            "flash": flash,
            "flash_kind": flash_kind,
        },
    )


# ---------------------------------------------------------------------------
# Team-member CRUD
# ---------------------------------------------------------------------------


@router.post("/admin/users")
def create_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    user: User = Depends(require_role(Role.admin)),
    db: Session = Depends(get_db),
):
    tenant_id = _resolve_tenant_id(user, db)
    if not tenant_id:
        _flash(request, "No client selected.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    name = name.strip()
    email = email.strip().lower()
    try:
        role_enum = Role(role)
    except ValueError:
        _flash(request, "Invalid role.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    if role_enum not in _ADMIN_ASSIGNABLE:
        _flash(request, "You can only add viewers, operators, or admins.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    if not name or not email:
        _flash(request, "Name and email are required.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    if db.query(User).filter(User.email.ilike(email)).first():
        _flash(request, f"Email {email} is already in use.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    new_user = User(tenant_id=tenant_id, email=email, name=name, role=role_enum)
    db.add(new_user)
    _audit(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        action="user_created",
        detail=f"Added {role_enum.value} {email}",
    )
    db.commit()
    _flash(request, f"Added {name} ({role_enum.value}).")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/role")
def change_user_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    user: User = Depends(require_role(Role.admin)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")

    tenant_id = _resolve_tenant_id(user, db)
    # Admin can only modify users within their own client; owner may modify any non-owner.
    if user.role is not Role.owner and target.tenant_id != tenant_id:
        raise HTTPException(403, "Cannot modify users outside your client")
    if target.role is Role.owner:
        raise HTTPException(403, "Cannot modify the system owner")
    if target.id == user.id:
        _flash(request, "You can't change your own role.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        role_enum = Role(role)
    except ValueError:
        _flash(request, "Invalid role.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    if role_enum not in _ADMIN_ASSIGNABLE:
        _flash(request, "You can only assign viewer, operator, or admin.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    old = target.role.value
    target.role = role_enum
    _audit(
        db,
        tenant_id=target.tenant_id,
        user_id=user.id,
        action="user_role_changed",
        detail=f"{target.email}: {old} → {role_enum.value}",
    )
    db.commit()
    _flash(request, f"{target.name} is now {role_enum.value}.")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    user: User = Depends(require_role(Role.admin)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")

    tenant_id = _resolve_tenant_id(user, db)
    if user.role is not Role.owner and target.tenant_id != tenant_id:
        raise HTTPException(403, "Cannot delete users outside your client")
    if target.role is Role.owner:
        raise HTTPException(403, "Cannot delete the system owner")
    if target.id == user.id:
        _flash(request, "You can't delete yourself.", "err")
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    name, email = target.name, target.email
    target_tenant = target.tenant_id
    db.delete(target)
    _audit(
        db,
        tenant_id=target_tenant,
        user_id=user.id,
        action="user_deleted",
        detail=f"Removed {email}",
    )
    db.commit()
    _flash(request, f"Removed {name}.")
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
