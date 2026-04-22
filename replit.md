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
