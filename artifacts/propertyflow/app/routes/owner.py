"""System-owner panel — cross-client view, AI health, analytics, client CRUD."""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import AuditLog, Item, ItemStatus, Role, Tenant, User
from app.services.ai_service import ai

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Minutes saved per AI-assisted item (manual draft ~15 min, reviewed AI draft ~3 min)
_MINUTES_SAVED_PER_AI_ITEM = 12


def _ts(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _fmt_response(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    if minutes < 60:
        return f"{int(round(minutes))}m"
    return f"{minutes / 60:.1f}h"


def _audit(db: Session, *, tenant_id, user_id, action: str, detail: str = "") -> None:
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action=action, detail=detail))


@router.get("/owner")
def owner_home(request: Request, user: User = Depends(require_role(Role.owner)), db: Session = Depends(get_db)):
    tenants = db.query(Tenant).order_by(Tenant.name).all()
    rows = []
    system_totals = {"total": 0, "done": 0, "ai_drafted": 0, "response_mins": []}

    for t in tenants:
        all_items: list[Item] = db.query(Item).filter(Item.tenant_id == t.id).all()
        user_count = db.query(func.count(User.id)).filter(User.tenant_id == t.id).scalar() or 0

        total = len(all_items)
        done_items = [it for it in all_items if it.status == ItemStatus.done]
        open_count = total - len(done_items)
        ai_drafted = sum(1 for it in all_items if it.draft_reply)

        response_mins: list[float] = []
        for it in done_items:
            a, b = _ts(it.created_at), _ts(it.updated_at)
            if a and b and b > a:
                response_mins.append((b - a).total_seconds() / 60.0)

        avg_min = (sum(response_mins) / len(response_mins)) if response_mins else None
        ai_rate = round(ai_drafted / total * 100) if total else 0
        est_hours = round(ai_drafted * _MINUTES_SAVED_PER_AI_ITEM / 60, 1)

        rows.append({
            "tenant": t,
            "users": user_count,
            "total": total,
            "done": len(done_items),
            "open": open_count,
            "avg_response_min": avg_min,
            "avg_response": _fmt_response(avg_min),
            "ai_rate": ai_rate,
            "ai_drafted": ai_drafted,
            "est_hours": est_hours,
        })

        system_totals["total"] += total
        system_totals["done"] += len(done_items)
        system_totals["ai_drafted"] += ai_drafted
        system_totals["response_mins"].extend(response_mins)

    all_mins = system_totals["response_mins"]
    system_avg = _fmt_response((sum(all_mins) / len(all_mins)) if all_mins else None)
    total_est_hours = round(system_totals["ai_drafted"] * _MINUTES_SAVED_PER_AI_ITEM / 60, 1)
    system_ai_rate = (
        round(system_totals["ai_drafted"] / system_totals["total"] * 100)
        if system_totals["total"] else 0
    )

    summary = {
        "clients": len(tenants),
        "total": system_totals["total"],
        "done": system_totals["done"],
        "avg_response": system_avg,
        "est_hours": total_est_hours,
        "ai_rate": system_ai_rate,
    }

    audit = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()

    # Tenant lookup for human-readable audit detail
    tenant_names = {t.id: t.name for t in tenants}

    flash = request.session.pop("flash", None)
    flash_kind = request.session.pop("flash_kind", "ok")

    return templates.TemplateResponse(
        request,
        "owner.html",
        {
            "user": user,
            "rows": rows,
            "audit": audit,
            "ai_status": ai.status(),
            "summary": summary,
            "tenant_names": tenant_names,
            "flash": flash,
            "flash_kind": flash_kind,
        },
    )


# ---------------------------------------------------------------------------
# Client (tenant) create / delete + initial admin
# ---------------------------------------------------------------------------


def _flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session["flash"] = msg
    request.session["flash_kind"] = kind


@router.post("/owner/clients")
def create_client(
    request: Request,
    name: str = Form(...),
    admin_name: str = Form(""),
    admin_email: str = Form(""),
    user: User = Depends(require_role(Role.owner)),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        _flash(request, "Client name is required.", "err")
        return RedirectResponse("/owner", status_code=status.HTTP_303_SEE_OTHER)

    if db.query(Tenant).filter(Tenant.name.ilike(name)).first():
        _flash(request, f"A client named “{name}” already exists.", "err")
        return RedirectResponse("/owner", status_code=status.HTTP_303_SEE_OTHER)

    tenant = Tenant(name=name)
    db.add(tenant)
    db.flush()  # get tenant.id

    detail = f"Created client {name!r}"

    admin_email = admin_email.strip().lower()
    admin_name = admin_name.strip()
    if admin_email:
        if db.query(User).filter(User.email.ilike(admin_email)).first():
            db.rollback()
            _flash(request, f"Email {admin_email} already in use.", "err")
            return RedirectResponse("/owner", status_code=status.HTTP_303_SEE_OTHER)
        admin = User(
            tenant_id=tenant.id,
            email=admin_email,
            name=admin_name or admin_email.split("@")[0].title(),
            role=Role.admin,
        )
        db.add(admin)
        detail += f"; added admin {admin_email}"

    _audit(db, tenant_id=tenant.id, user_id=user.id, action="client_created", detail=detail)
    db.commit()
    _flash(request, f"Client “{name}” created." + (f" Admin {admin_email} added." if admin_email else ""))
    return RedirectResponse("/owner", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/owner/clients/{tenant_id}/delete")
def delete_client(
    request: Request,
    tenant_id: int,
    user: User = Depends(require_role(Role.owner)),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Client not found")
    name = tenant.name
    db.delete(tenant)  # cascades to users + items + tasks
    _audit(db, tenant_id=None, user_id=user.id, action="client_deleted", detail=f"Deleted client {name!r}")
    db.commit()
    _flash(request, f"Client “{name}” deleted.")
    return RedirectResponse("/owner", status_code=status.HTTP_303_SEE_OTHER)
