# PropertyFlow — Product Overview for Competitive Analysis

## What it is

PropertyFlow is a **multi-tenant SaaS workflow tool for residential lettings and property management agencies**. It sits between a property manager's inbox/portals and the people who actually do the work (operators, maintenance dispatchers, contractors, viewing agents), and it uses AI to triage, draft replies, and route every incoming request to the right person with an SLA attached.

Think of it as a hybrid of a **property-management CRM**, a **shared inbox/helpdesk**, and a **contractor dispatch system**, with an AI layer doing the first pass on every message.

Direct competitors to benchmark it against: **Arthur Online, Re-Leased, FixFlo, PayProp, Propertyware, Buildium, AppFolio**, plus generic shared-inbox tools like **Front** and **HappyCo** for maintenance.

---

## Who it's for

A typical customer is a lettings agency or property management company managing dozens to thousands of rental units, where a small ops team fields a constant stream of tenant emails, viewing requests, landlord queries, and maintenance reports — and routinely hands maintenance jobs to outside contractors (plumbers, electricians, etc.).

It supports two organizational shapes out of the box:

- **Single-firm:** the agency uses its own in-house contractors.
- **Multi-firm:** the agency works with several independent contractor companies (e.g. a heating firm and an electrical firm) and needs strict separation between them.

---

## Roles and who sees what

Six roles, each with a tailored dashboard:

| Role | Purpose |
|------|---------|
| **Owner** | Cross-tenant superuser. Sees system health, AI status, all tenants. |
| **Admin** (client admin) | Manages users, contractor companies, and audit logs for one tenant. |
| **Operator** | Front-line ops. Triages tickets, sends replies, dispatches maintenance to a contractor company. |
| **Viewer** | Read-only access for stakeholders. |
| **Contractor Admin** (dispatcher) | Receives maintenance handoffs for their firm and assigns them to a specific contractor on their team. |
| **Contractor** | Field worker. Sees only the jobs assigned to them, marks them complete with a note. |

Crucially, **contractor_admin and contractor users are scoped to a single contractor company**. A heating dispatcher cannot see, open, or assign tickets that were sent to the electrical firm — even by guessing the URL. This isolation is enforced at the route level.

---

## Core feature set

### 1. Unified ticket inbox ("items")

Every inbound thing — tenant email, viewing request, maintenance report, landlord question, payment chase — lands as an **Item** with sender name, subject, body, status, urgency, and category. The dashboard shows a Kanban-style board grouped by status (`new → in_progress → awaiting_reply → done`) plus a personal "My Open Tasks" panel.

### 2. AI triage and draft replies

On ingest, the app calls a local **Gemma 3n** model (via Ollama) to:

- **Classify** the item into a category (maintenance, viewing, landlord, general, payment chase) and an urgency level (low/medium/high).
- **Generate a draft reply** in the agency's voice that the operator can review, regenerate, or send.

If the AI is unavailable, it silently falls back to a deterministic keyword-based classifier so the queue never stalls. Each item shows which mode produced it (`ollama` vs `fallback`), and the owner panel surfaces live AI health.

### 3. Automatic routing and SLA assignment

A single workflow engine (`workflow_service.ingest_item`) classifies, assigns to the right role, generates the draft, creates the first task with an SLA-based due date, and writes an audit-log entry — all in one transaction. Routing rules are category→role; SLA hours are urgency→due offset (high-urgency items get tight deadlines).

### 4. Multi-company contractor dispatch (the differentiator)

This is where PropertyFlow goes beyond most shared-inbox tools:

- A client admin registers the contractor companies they work with (e.g. "Acme Heating & Plumbing", "Sparkright Electricians") and assigns dispatcher/contractor users to each.
- When the operator clicks **Send** on a maintenance ticket, they pick **which firm** the job goes to from a dropdown on the item page.
- The system creates a handoff task assigned to a dispatcher in **that exact firm**. If no dispatcher exists in that firm, the task stays unassigned rather than silently leaking to a different firm.
- The dispatcher then assigns it to one of their own contractors. They cannot assign to a contractor in a sibling firm.
- The contractor sees only their own job, marks it complete with a note, and the parent item auto-closes when no open tasks remain.

A "Dispatched to Sparkright Electricians" strip is visible to everyone on the ticket so accountability is obvious.

### 5. Status lifecycle with enforced transitions

Items move through a strict state machine (`new → in_progress → awaiting_reply | done`, with `done` reopenable by ops only). Completing the last open task auto-closes the item. Closing a maintenance triage auto-spawns the contractor handoff task. This prevents the "dead ticket" problem common in email-based ops.

### 6. Audit log

Every classification, assignment, status change, draft regeneration, and dispatch event is recorded with actor, timestamp, and detail. Admins see their tenant's log; the owner sees the full system log. This is genuinely useful for landlord disputes and compliance.

### 7. Magic-link auth via Resend

Passwordless login over email, single-use tokens with nonce rotation (so a forwarded link cannot be replayed), 15-minute expiry. No password reset flows to maintain. Sessions are signed cookies.

### 8. Multi-tenant isolation

Every operational row carries a `tenant_id`. Users from Acme Lettings cannot see anything from Beech Property Group. The owner role is the only one that can cross tenants, and only via a separate panel.

### 9. Connector framework (extensibility)

A `Connector` protocol with stub adapters for **Google Sheets** and **email inbox** polling already wired against the same `ingest_item` entrypoint the AI demo uses. Real polling against rental portals (Rightmove, Zoopla), Gmail, or property-management feeds is a small lift on top.

### 10. Manual create and demo scenarios

Operators can create a ticket by hand from the dashboard. There are also four pre-built demo scenarios (boiler breakdown, viewing request, landlord query, payment chase) that flow through the real pipeline — useful for sales demos and for testing the AI end-to-end.

---

## Use case scenarios for competitor benchmarking

### Scenario A — Out-of-hours boiler breakdown

A tenant emails at 11pm: *"My boiler is leaking and there's no hot water."*

1. The email lands as an item. AI classifies it as **maintenance / high urgency**, generates a calming draft reply, sets a 2-hour SLA, and assigns triage to operator Maria.
2. Maria opens the item the next morning, sees the AI draft, picks **Acme Heating & Plumbing** from the dispatch dropdown, and clicks Send.
3. The reply goes to the tenant; a handoff task is created and routed to Mike, the heating firm's dispatcher.
4. Mike opens the ticket, assigns it to Carl (heating engineer). Carl sees the job on his "My Open Tasks" panel, attends, and marks it complete with a note: *"Replaced pressure valve."*
5. The parent item auto-closes. The full timeline — every actor, every timestamp — is preserved in the audit log for the landlord's records.

**Compare against:** FixFlo (maintenance only, no inbox), Arthur (full PMS but weaker AI triage), Front (great inbox, no contractor dispatch model).

### Scenario B — Multi-firm separation under one agency

Acme Lettings uses two contractor firms. A leaking radiator and a faulty light switch arrive in the same hour.

1. Maria dispatches the radiator to **Acme Heating** and the light switch to **Sparkright Electricians**.
2. Mike (heating dispatcher) only sees the radiator job. He cannot open the light switch ticket even by guessing its URL.
3. Eve (Sparkright dispatcher) only sees the light switch job. She tries to assign it to Carl (heating contractor) — the system rejects it as a cross-firm assignment.
4. Each firm sees a clean queue containing only their own work, while Maria and the admin keep a single unified view.

**Compare against:** most PMS tools either treat all contractors as one pool (no firm separation) or require a separate vendor portal per firm (no shared-inbox view).

### Scenario C — Viewing request flood

Five viewing requests arrive in twenty minutes after a new listing goes live.

1. AI classifies each as **viewing / medium urgency**, drafts a reply with available slots, and assigns to the lettings team.
2. Priya batch-reviews, regenerates one draft she doesn't like, and sends all five with one click each.
3. Items move to `awaiting_reply`. When tenants confirm, Priya marks them `done`.

**Compare against:** generic CRMs that require manual templates per response.

### Scenario D — Landlord query with audit trail

A landlord asks: *"What was actually done at 14 Elm Crescent last Tuesday?"*

The admin opens the audit log filtered by item, exports the timeline (classification, dispatch firm chosen, contractor assigned, completion note, timestamps) and forwards it. No reconstruction from emails.

**Compare against:** email-based workflows where this evidence simply doesn't exist.

### Scenario E — Payment chase

A monthly batch of overdue tenants needs gentle but firm reminders.

1. Items are ingested via the connector framework (e.g. from a Google Sheet of arrears).
2. AI categorizes each as **payment chase**, drafts a tone-appropriate reply, and routes to the finance operator with a 24-hour SLA.
3. The finance operator reviews drafts and sends, with the audit log capturing every send for compliance.

---

## Technical posture (relevant for "is this real?" comparisons)

- **Backend:** Python 3, FastAPI, SQLAlchemy, SQLite (Postgres-ready via DATABASE_URL).
- **AI:** Local Gemma 3n via Ollama, with an OpenRouter path also wired. Deterministic fallback keeps the workflow alive when the model is offline.
- **UI:** Server-rendered Jinja2 + Tailwind. Fast, accessible, works without JavaScript for the critical paths.
- **Auth:** Magic-link over Resend, signed-cookie sessions, single-use tokens with nonce rotation, dev-only test-domain bypass gated behind an env flag.
- **Isolation:** Tenant-level and contractor-company-level enforcement at the route layer, not just the UI — verified by direct-URL probe tests.
- **Audit:** Every state-changing action writes an audit row.

---

## Honest competitive positioning

**Strengths to lead with:**

- Multi-firm contractor model with hard isolation — uncommon in this category.
- AI triage + drafting baked into the same workflow as routing, not bolted on.
- Real audit trail and SLA enforcement, not just a board.
- Clean role model with six well-scoped personas.
- Local AI option means tenant data never leaves the agency's infrastructure.

**Gaps to acknowledge versus mature PMS suites:**

- No tenancy/lease/rent-ledger module (Arthur, Re-Leased, AppFolio all have this).
- No tenant-facing portal yet (FixFlo and Arthur do).
- Inbound channels are stub connectors — real Gmail/portal polling would need to be turned on.
- No mobile app for contractors yet (the web view is mobile-friendly but not native).

That gives you a clear story: PropertyFlow is the **AI-native triage and dispatch layer** that the legacy PMS players don't have, and it can either complement them or replace the inbox-and-contractor parts of their offering.
