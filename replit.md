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
- `scenarios.py` — 4 pre-baked demo payloads (tenant_enquiry, maintenance, viewing, landlord_admin)
- `templates/index.html` + `static/app.js` — Tailwind CDN single-page UI: inbox / detail / action panels + 4-column workflow board, polls `/api/state` every 4s

**Extending:**
- Swap rule-based classifier for an LLM by replacing the body of `workflow.classify_input` — nothing else changes
- Swap JSON store for SQLite by replacing `store.py` functions; signatures stay the same
- Add input connectors (Gmail, webhooks) by hitting `POST /ingest` with `{from_name, message, property, type?}`
