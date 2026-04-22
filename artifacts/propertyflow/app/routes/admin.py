"""Admin panel — client (tenant)-level user management, items, audit log."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import AuditLog, Item, Role, Tenant, User

_AUDIT_PAGE_SIZE = 25

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Roles a client admin is allowed to assign to other users in their own client.
_ADMIN_ASSIGNABLE = {Role.viewer, Role.contractor, Role.contractor_admin, Role.operator, Role.admin}
# A contractor admin can only add/manage other contractors (no operators,
# admins, or other contractor admins).
_CONTRACTOR_ADMIN_ASSIGNABLE = {Role.contractor}


def _assignable_for(actor: User) -> set[Role]:
    if actor.role is Role.contractor_admin:
        return _CONTRACTOR_ADMIN_ASSIGNABLE
    return _ADMIN_ASSIGNABLE


def _visible_users_for(actor: User, db: Session, tenant_id):
    """Contractor admins only see contractors in the user list — they don't
    need (or get) visibility into the full team roster."""
    if not tenant_id:
        return []
    q = db.query(User).filter(User.tenant_id == tenant_id)
    if actor.role is Role.contractor_admin:
        q = q.filter(User.role == Role.contractor)
    return q.order_by(User.role, User.name).all()


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
def admin_home(
    request: Request,
    user: User = Depends(require_role(Role.admin, Role.contractor_admin)),
    db: Session = Depends(get_db),
    event: str = "",
    actor: str = "",
    q: str = "",
    page: int = 1,
):
    tenant_id = _resolve_tenant_id(user, db)

    users = _visible_users_for(user, db, tenant_id)
    items = (
        db.query(Item).filter(Item.tenant_id == tenant_id).order_by(Item.created_at.desc()).limit(100).all()
        if tenant_id else []
    )

    # Searchable, paginated audit feed. Uses the existing AuditLog table —
    # no parallel "events" store. Filters: event type (action), actor (user
    # id), free-text on detail.
    audit_filters = {"event": event, "actor": actor, "q": q.strip()}
    audit, total_audit, page = _query_audit(db, tenant_id, audit_filters, page)

    # Facet values for the filter dropdowns — only show events / actors that
    # actually exist within this tenant, so the UI doesn't lie about scope.
    if tenant_id:
        event_choices = [
            r[0] for r in db.query(AuditLog.action).filter(AuditLog.tenant_id == tenant_id).distinct().all()
        ]
    else:
        event_choices = []
    event_choices.sort()

    tenant = db.get(Tenant, tenant_id) if tenant_id else None

    flash = request.session.pop("flash", None)
    flash_kind = request.session.pop("flash_kind", "ok")

    page_count = max(1, (total_audit + _AUDIT_PAGE_SIZE - 1) // _AUDIT_PAGE_SIZE)
    actor_choices = users  # already scoped to this tenant

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "tenant": tenant,
            "users": users,
            "items": items,
            "audit": audit,
            "audit_total": total_audit,
            "audit_page": page,
            "audit_page_count": page_count,
            "audit_filters": audit_filters,
            "event_choices": event_choices,
            "actor_choices": actor_choices,
            "assignable_roles": [r for r in (Role.viewer, Role.contractor, Role.contractor_admin, Role.operator, Role.admin) if r in _assignable_for(user)],
            "flash": flash,
            "flash_kind": flash_kind,
        },
    )


def _query_audit(db: Session, tenant_id, filters: dict, page: int):
    if not tenant_id:
        return [], 0, 1
    query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    if filters.get("event"):
        query = query.filter(AuditLog.action == filters["event"])
    if filters.get("actor"):
        try:
            query = query.filter(AuditLog.user_id == int(filters["actor"]))
        except (TypeError, ValueError):
            pass
    if filters.get("q"):
        like = f"%{filters['q']}%"
        query = query.filter(AuditLog.detail.ilike(like))
    total = query.count()
    page = max(1, page)
    rows = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * _AUDIT_PAGE_SIZE)
        .limit(_AUDIT_PAGE_SIZE)
        .all()
    )
    return rows, total, page


# ---------------------------------------------------------------------------
# Team-member CRUD
# ---------------------------------------------------------------------------


@router.post("/admin/users")
def create_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    user: User = Depends(require_role(Role.admin, Role.contractor_admin)),
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

    allowed = _assignable_for(user)
    if role_enum not in allowed:
        _flash(request, "You don't have permission to add that role.", "err")
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
    user: User = Depends(require_role(Role.admin, Role.contractor_admin)),
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

    allowed = _assignable_for(user)
    # Contractor admins can only modify contractors and only re-assign them
    # within the same restricted set.
    if user.role is Role.contractor_admin and target.role is not Role.contractor:
        raise HTTPException(403, "Contractor admins can only manage contractors")
    if role_enum not in allowed:
        _flash(request, "You don't have permission to assign that role.", "err")
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
    user: User = Depends(require_role(Role.admin, Role.contractor_admin)),
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
    # Contractor admins can only delete contractors.
    if user.role is Role.contractor_admin and target.role is not Role.contractor:
        raise HTTPException(403, "Contractor admins can only manage contractors")
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
