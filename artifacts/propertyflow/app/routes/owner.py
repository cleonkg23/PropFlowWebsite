"""System-owner panel — cross-tenant view + AI health + analytics."""
from __future__ import annotations

from datetime import timezone

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

        # Avg response time: creation → last-update for resolved items
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

    # System-wide summary metrics
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

    return templates.TemplateResponse(
        request,
        "owner.html",
        {"user": user, "rows": rows, "audit": audit, "ai_status": ai.status(), "summary": summary},
    )
