"""Demo seeder — runs once on first boot when the DB is empty.

Creates two tenants so multi-tenancy is visible immediately, plus the
roster of users (one per role) and a handful of pre-classified items.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Item, ItemStatus, Role, Task, TaskStatus, Tenant, Urgency, User


def seed_if_empty(db: Session) -> None:
    if db.query(Tenant).first():
        return

    # Tenants
    acme = Tenant(name="Acme Lettings")
    beech = Tenant(name="Beech Property Group")
    db.add_all([acme, beech])
    db.flush()

    # All seed accounts use @test.test so they sign in instantly without
    # requiring a magic-link email — see app/auth.py:is_test_email.
    owner = User(email="owner@test.test", name="System Owner", role=Role.owner)

    # Acme users
    acme_admin = User(tenant_id=acme.id, email="sarah.acme@test.test", name="Sarah Admin", role=Role.admin)
    maria = User(tenant_id=acme.id, email="maria.acme@test.test", name="Maria Operator", role=Role.operator)
    priya = User(tenant_id=acme.id, email="priya.acme@test.test", name="Priya Operator", role=Role.operator)
    viewer = User(tenant_id=acme.id, email="vince.acme@test.test", name="Vince Viewer", role=Role.viewer)

    # Beech: just an admin so the owner panel shows two tenants populated
    beech_admin = User(tenant_id=beech.id, email="tom.beech@test.test", name="Tom Admin", role=Role.admin)

    db.add_all([owner, acme_admin, maria, priya, viewer, beech_admin])
    db.flush()

    # Sample items in Acme (already classified, sitting in the board so it
    # never starts empty — the demo flow adds new ones on top of these).
    samples = [
        Item(
            tenant_id=acme.id,
            subject="Boiler out at 14 Park Road",
            body="URGENT — boiler is out, no hot water since last night. Two kids in the flat, please can someone come today.",
            sender_name="Mr Patel",
            sender_email="patel@example.com",
            category="maintenance",
            urgency=Urgency.high,
            status=ItemStatus.in_progress,
            assigned_user_id=maria.id,
            draft_reply="Hi Mr Patel,\n\nSorry to hear that — I've logged this as urgent and a contractor will be in touch within 2 hours.\n\nBest,\nAcme Lettings",
            ai_mode="seed",
        ),
        Item(
            tenant_id=acme.id,
            subject="Re: viewing at 22 Elm",
            body="Thanks for the viewing yesterday — really liked it. Could we book a second viewing this week?",
            sender_name="James Wright",
            sender_email="james@example.com",
            category="viewing",
            urgency=Urgency.medium,
            status=ItemStatus.awaiting_reply,
            assigned_user_id=priya.id,
            draft_reply="Hi James,\n\nGreat to hear — I can offer Wednesday afternoon or Thursday morning. Which works?\n\nBest,\nAcme Lettings",
            ai_mode="seed",
        ),
        Item(
            tenant_id=acme.id,
            subject="Q4 statement request",
            body="Could I get the Q4 landlord statement for the three properties, plus a note on the gas safety renewal that was due last month?",
            sender_name="Mrs Holloway",
            sender_email="holloway@example.com",
            category="landlord_admin",
            urgency=Urgency.medium,
            status=ItemStatus.new,
            assigned_user_id=acme_admin.id,
            draft_reply=None,
            ai_mode="seed",
        ),
        Item(
            tenant_id=acme.id,
            subject="Deposit return chase",
            body="Chasing on the deposit return — second time asking, can someone pick this up please?",
            sender_name="Daniel Brooks",
            sender_email="daniel@example.com",
            category="tenant_enquiry",
            urgency=Urgency.high,
            status=ItemStatus.new,
            ai_mode="seed",
        ),
    ]
    db.add_all(samples)
    db.flush()

    # A couple of open tasks
    db.add_all([
        Task(
            tenant_id=acme.id,
            item_id=samples[0].id,
            description="Triage fault and dispatch contractor",
            assigned_user_id=maria.id,
            due_at=datetime.utcnow() + timedelta(hours=2),
            status=TaskStatus.open,
        ),
        Task(
            tenant_id=acme.id,
            item_id=samples[1].id,
            description="Confirm second viewing slot",
            assigned_user_id=priya.id,
            due_at=datetime.utcnow() + timedelta(hours=24),
            status=TaskStatus.open,
        ),
    ])
    db.commit()
