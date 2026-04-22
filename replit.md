# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## Apps in this repo

### `artifacts/property-workflow/` — marketing site
Static HTML/CSS/JS editorial site for "Property Workflow Co." Built/served by `serve.mjs`. Cream + forest-green palette, Fraunces + Inter, hairline rules. Designed for GitHub Pages export from `dist/`.

### `artifacts/workflow-demo/` — FastAPI demo (Python 3.11)
Standalone Python service that demonstrates the actual product the marketing site sells. Not registered as a workspace artifact (no Python artifact type exists), runs as a workflow on port 8000, accessible via the workflow's webview tab.

**Layered architecture per spec:**
- `main.py` — FastAPI app, routes (`/`, `/ingest`, `/demo/{key}`, `/api/state`, `/api/reset`)
- `workflow.py` — pure functions: `classify_input` (rules over keywords), `determine_workflow` (owner + SLA), `generate_draft_response` (templated), `create_task`, top-level `ingest()` orchestrator
- `store.py` — JSON-file persistence at `data/store.json` with a thread lock; functions: `add_item`, `add_task`, `update_item`, `get_state`, `reset`
- `scenarios.py` — 4 pre-baked scenarios (tenant_enquiry, maintenance, viewing, landlord_admin) + `PRESSURE_ITEMS` (chasers seeded into the inbox so the demo never starts empty)
- `templates/index.html` + `static/app.js` — Tailwind CDN single-page UI: hero with before/after framing, 5-step indicator (Received → Classified → Assigned → Reply ready → Tracked), inbox / classification / action panels, 4-column workflow board, value caption beneath. Polls `/api/state` every 4s when idle; polling is paused during the guided flow.

**Guided flow (the "demo story"):**
Triggered by a scenario button. `runGuidedFlow(key)` in `app.js`:
1. POST `/demo/{key}`, capture returned `item_id`, pull state.
2. **Inbox** highlighted, new row flashes + scrolls into view.
3. Sibling inbox rows dim, selected row stays prominent.
4. **Classification** panel goes active; the four fields (category → urgency → owner → next action) reveal in sequence via `.stage` → `.stage.show`, each with a one-line "why" caption.
5. **Task** card fades in; **draft reply** fades in after; status buttons last.
6. **Workflow board** highlights, the new card appears in its destination column with a soft rise animation + ring.
7. Italic value line ("Nothing gets missed…") fades in beneath the board. Section dimming clears, polling resumes.

Only one flow runs at a time (`flowRunning` flag); polling skipped while a flow is active so the staged reveal isn't clobbered.

**Endpoints:**
- `GET /` — page
- `GET /api/state` — full state (polled)
- `POST /api/reset` — wipe store
- `POST /api/seed-pressure` — idempotent: adds PRESSURE_ITEMS only if store is empty (called on first load + after reset)
- `POST /ingest` — generic ingest `{from_name, message, property, type?}`
- `POST /demo/{key}` — run a named scenario through ingest
- `POST /api/items/{id}/status` — transition with validation in `workflow.update_status`

**Visual language:** cream `#f3eee4`, ink `#1f2a24`, forest green `#2f6b53`, rule `#dcd3c0`. Fraunces (serif headings) + Inter (UI). Tasteful animation only: fade, slide-up, soft glow ring, staggered stage reveals — no bouncing/neon/spinners. Section emphasis = `.section.active` (green ring + soft shadow) and `.section.dim` (opacity 0.42).

**Extending:**
- Swap rule-based classifier for an LLM by replacing the body of `workflow.classify_input` — nothing else changes
- Swap JSON store for SQLite by replacing `store.py` functions; signatures stay the same
- Add input connectors (Gmail, webhooks) by hitting `POST /ingest` with `{from_name, message, property, type?}`
- Add a new scenario by adding an entry to `SCENARIOS` in `scenarios.py` — the guided flow code is scenario-agnostic and will pick it up automatically

### `artifacts/propertyflow/` — multi-tenant FastAPI app (Python 3.11)
Production-leaning version of the workflow-demo. Real persistence, real auth, real local AI, real role separation. Registered as a `web` artifact (id `artifacts/propertyflow`, library `previewPath="/app"`, port **8008**) so it appears in the workspace library alongside the marketing site and api-server. Because templates use root-relative URLs (`/login`, `/dashboard`, …), `app/middleware/prefix.PrefixMiddleware` transparently makes the app prefix-aware when mounted at `/app`: it sets `scope["root_path"]` so Starlette's `get_route_path` strips the prefix during routing, rewrites HTML `href`/`action`/`src`/`formaction` attributes to prepend `/app`, and rewrites `Location` headers on redirects. The middleware is enabled by `PROPERTYFLOW_URL_PREFIX=/app` (set in the artifact toml); when that env var is empty the middleware is a no-op so direct port access still works for local dev.

**Layout:**
- `app/db.py` — SQLAlchemy engine, `SessionLocal`, `Base`, `get_db()`, `init_db()`. SQLite at `data/propertyflow.db`, override via `PROPERTYFLOW_DB_URL`.
- `app/models.py` — `Tenant`, `User` (roles: `owner|admin|operator|viewer`), `Item` (status: `new|in_progress|awaiting_reply|done`, urgency: `low|medium|high`), `Task`, `AuditLog`. Multi-tenant by `tenant_id` FK on every operational row; `owner` users have `tenant_id = NULL` and cross tenants.
- `app/auth.py` — Starlette `SessionMiddleware` signed-cookie auth keyed off `SESSION_SECRET`. Magic-link login via Resend (15-min `itsdangerous` tokens). **Single-use enforced**: each token embeds the user's current `auth_nonce`; `consume_magic_token` rotates the nonce on success, invalidating the token and any siblings. Test-domain bypass (`@test.test` → instant login) is **gated behind `PROPERTYFLOW_DEV=1`** so it cannot accidentally activate in production. Raises if `SESSION_SECRET` is missing. `current_user` (optional), `require_user`, `require_role(*roles)` deps. `owner` passes every role check.
- `app/services/email_service.py` — Resend client; fetches API key + from_email from the Replit connector API per-send (never cached). Never logs full magic URLs/tokens (bearer credentials). On send failure: in dev mode (`PROPERTYFLOW_DEV=1`) the route surfaces the link inline; in prod it shows a generic "try again" message.
- `app/seed.py` — runs once on first boot when DB is empty. Creates two tenants (Acme Lettings, Beech Property Group), one user per role plus a system owner, and a handful of pre-classified items + open tasks so the board never starts empty.
- `app/services/ai_service.py` — `AIService` with `classify_item()` and `generate_draft()`. Calls local Ollama (`gemma3n:e4b`, default `http://localhost:11434`) via `httpx` non-streaming; on any failure (connection, timeout, malformed JSON) falls back to deterministic keyword rules. Returns the `mode` it used (`ollama` or `fallback`) which is recorded on the item and surfaced in the UI. `status()` is a 2s health probe used by the owner panel.
- `app/services/workflow_service.py` — single engine. `ingest_item` runs the full pipeline (classify → assign → draft → task) inside one DB transaction and writes an audit log line. Routing rule = category → role; SLA hours = urgency → due_at offset. `update_status` enforces a transition table (`new→in_progress`, `in_progress→awaiting_reply|done`, `awaiting_reply→in_progress|done`, `done→∅`) and auto-closes open tasks on completion. `assign_user` mirrors the assignment onto the open task. `regenerate_draft` reruns the model only.
- `app/services/connectors/` — adapter interface (`Connector` Protocol over `IngestPayload`) + `google_sheets.py` and `email_inbox.py` stubs, ready to wire real polling against the `ingest_item` entrypoint.
- `app/routes/` —
  - `public.py`: `/`, `/login` (GET+POST, email lookup, redirect by role), `/logout`
  - `dashboard.py`: `/dashboard` (board grouped by status, "my open tasks", manual create form — contractors only see items they're assigned to), `/items/{id}` (subject/body, classification, draft + Regenerate, assignment dropdown, status transition buttons; contractors see a focused "Your assignment" panel and can mark their own tasks complete with a note), plus form-post handlers for status/assign/regenerate, per-task complete (`POST /tasks/{id}/complete`, auto-closes the parent item when no open tasks remain; auto-spawns a contractor handoff task when ops completes a maintenance triage), and reopen (`POST /items/{id}/reopen`, ops-only)
  - `admin.py`: `/admin` — tenant users + recent items + tenant audit log (admin/owner only; owner without tenant falls back to first tenant)
  - `owner.py`: `/owner` — cross-tenant counts + AI health card + system audit log (owner only)
  - `api.py`: `POST /api/items` (JSON ingest, scoped to caller's tenant), `POST /demo/{key}` (4 demo scenarios — boiler/viewing/landlord/chase — that go through the full real pipeline)
- `app/main.py` — FastAPI factory + `lifespan` (init_db + seed_if_empty), `SessionMiddleware`, static mount at `/static`, all routers included.
- `templates/` — server-rendered Jinja2 with Tailwind CDN. `base.html`, `_components/{nav,board}.html`, `login.html`, `dashboard.html`, `item_detail.html`, `admin.html`, `owner.html`. Role-aware nav, status-tone badges, AI-mode badge on every item card.
- `static/app.js` — small vanilla JS for quick-login buttons and the manual-create JSON post.

**Demo logins:** `owner@propertyflow.dev`, `admin@acme.dev`, `maria@acme.dev`, `priya@acme.dev`, `viewer@acme.dev`, `admin@beech.dev`. No password — type/click and you're in.

**Local AI:** Ollama is installed under `~/.local/bin/ollama` and serves on `:11434`. Model is `gemma3n:e4b` (~4.5 GB). Service is the Ollama daemon, started in the background; install/pull logs at `/tmp/ollama_setup.log`. The app uses real AI when Ollama+model are present and silently degrades to deterministic rules otherwise — the owner panel surfaces which mode is live.

**Extending:**
- Add a connector: implement `Connector.fetch_new()` (yield `IngestPayload`s), then call `workflow_service.ingest_item(...)` for each — that's the entire integration point.
- Add a category/route: extend `ROUTING`, `NEXT_ACTION`, `CATEGORY_KEYWORDS` and the AI prompt's enum in `ai_service.py`.
- Swap SQLite for Postgres: set `PROPERTYFLOW_DB_URL` — no other changes.
- Magic-link auth via Resend is wired up. To send to *any* recipient (not just the Resend account owner), the user must verify a sending domain at https://resend.com/domains and set the matching `from_email` in Replit's Resend connector settings. Until then, sends to non-test emails will hit Resend's "domain not verified" error and the app falls back to showing the link inline.
