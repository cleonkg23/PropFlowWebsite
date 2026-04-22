"""Demo seeder — runs once on first boot when the DB is empty.

Creates two tenants so multi-tenancy is visible immediately, plus the
roster of users (one per role) and a handful of pre-classified items.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    ContractorCompany,
    Item,
    ItemStatus,
    Role,
    Task,
    TaskStatus,
    Tenant,
    Urgency,
    User,
)


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

    # Two contractor companies under Acme so the multi-company demo shows
    # immediately: a heating firm (Mike's team) and an electrical firm
    # (Eve's team). The operator picks which one gets a given handoff.
    heating_co = ContractorCompany(tenant_id=acme.id, name="Acme Heating & Plumbing")
    electrical_co = ContractorCompany(tenant_id=acme.id, name="Sparkright Electricians")
    db.add_all([heating_co, electrical_co])
    db.flush()

    # Heating company roster
    mike = User(
        tenant_id=acme.id, email="mike.dispatch@test.test", name="Mike Dispatch",
        role=Role.contractor_admin, contractor_company_id=heating_co.id,
    )
    carl = User(
        tenant_id=acme.id, email="carl.contractor@test.test", name="Carl Contractor",
        role=Role.contractor, contractor_company_id=heating_co.id,
    )
    # Second contractor in the same company — used to demo "contractors see
    # all of their company's work, not just their own assignments".
    nina = User(
        tenant_id=acme.id, email="nina.heating@test.test", name="Nina Heating",
        role=Role.contractor, contractor_company_id=heating_co.id,
    )

    # Electrical company roster — different dispatcher + crew
    eve = User(
        tenant_id=acme.id, email="eve.sparkright@test.test", name="Eve Sparkright",
        role=Role.contractor_admin, contractor_company_id=electrical_co.id,
    )
    sam = User(
        tenant_id=acme.id, email="sam.sparkright@test.test", name="Sam Sparkright",
        role=Role.contractor, contractor_company_id=electrical_co.id,
    )

    # Beech: just an admin so the owner panel shows two tenants populated
    beech_admin = User(tenant_id=beech.id, email="tom.beech@test.test", name="Tom Admin", role=Role.admin)

    db.add_all([owner, acme_admin, maria, priya, viewer, mike, carl, nina, eve, sam, beech_admin])
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
            # Already dispatched to the heating firm — Mike + Carl + Nina see it.
            contractor_company_id=heating_co.id,
            due_at=datetime.utcnow() + timedelta(hours=2),
            draft_reply="Hi Mr Patel,\n\nSorry to hear that — I've logged this as urgent and a contractor will be in touch within 2 hours.\n\nBest,\nAcme Lettings",
            ai_mode="seed",
        ),
        Item(
            tenant_id=acme.id,
            subject="Lights flickering at 22 Elm Crescent",
            body="The hallway lights have been flickering for two days and now the kitchen sockets are tripping the breaker. Tenant is worried about safety.",
            sender_name="Ms Okafor",
            sender_email="okafor@example.com",
            category="maintenance",
            urgency=Urgency.medium,
            status=ItemStatus.in_progress,
            assigned_user_id=priya.id,
            # Dispatched to the electrical firm — Eve + Sam see this one.
            contractor_company_id=electrical_co.id,
            due_at=datetime.utcnow() + timedelta(hours=6),
            draft_reply="Hi Ms Okafor,\n\nThanks for letting us know — an electrician will be in touch within the day to book a visit.\n\nBest,\nAcme Lettings",
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
            due_at=datetime.utcnow() - timedelta(hours=3),  # already overdue
            ai_mode="seed",
        ),
        Item(
            tenant_id=acme.id,
            subject="Smoke alarm replaced — 9 Cedar",
            body="Tenant reported the smoke alarm beeping. Replaced unit and tested. All clear.",
            sender_name="Acme Field Tech",
            sender_email="field@acme.test",
            category="maintenance",
            urgency=Urgency.low,
            status=ItemStatus.done,
            assigned_user_id=maria.id,
            completed_at=datetime.utcnow() - timedelta(hours=5),
            completion_note="Replaced 9V battery + tested. Logged for next gas safety visit.",
            ai_mode="seed",
        ),
    ]
    db.add_all(samples)
    db.flush()

    # A couple of open tasks. Notice the maintenance task already includes a
    # "Done when:" acceptance line — see workflow_service.NEXT_ACTION.
    db.add_all([
        Task(
            tenant_id=acme.id,
            item_id=samples[0].id,
            description=(
                "Triage fault and dispatch contractor. "
                "Done when: contractor confirmed and ETA recorded on this ticket."
            ),
            assigned_user_id=maria.id,
            due_at=datetime.utcnow() + timedelta(hours=2),
            status=TaskStatus.open,
        ),
        # Follow-up task already handed off to the contractor (Carl) — gives
        # the contractor demo account something to see on first login.
        Task(
            tenant_id=acme.id,
            item_id=samples[0].id,
            description=(
                "On-site visit at 14 Park Road — inspect and repair boiler. "
                "Done when: heat restored and a completion note added with what was done."
            ),
            assigned_user_id=carl.id,
            due_at=datetime.utcnow() + timedelta(hours=4),
            status=TaskStatus.open,
        ),
        # Electrical handoff already dispatched to Sparkright (Eve's team)
        Task(
            tenant_id=acme.id,
            item_id=samples[1].id,
            description=(
                "On-site visit at 22 Elm Crescent — investigate flickering "
                "lights and tripping breaker. Done when: cause identified, "
                "fix completed and a completion note added."
            ),
            assigned_user_id=sam.id,
            due_at=datetime.utcnow() + timedelta(hours=6),
            status=TaskStatus.open,
        ),
        Task(
            tenant_id=acme.id,
            item_id=samples[2].id,  # viewing item shifted from [1] to [2]
            description="Confirm second viewing slot. Done when: viewing date and time confirmed by tenant.",
            assigned_user_id=priya.id,
            due_at=datetime.utcnow() + timedelta(hours=24),
            status=TaskStatus.open,
        ),
    ])
    db.commit()
