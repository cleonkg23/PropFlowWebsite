# Property Workflow Application

A monorepo for a property workflow management application, encompassing a marketing site, a guided demo, and a multi-tenant SaaS application.

## Run & Operate

- `pnpm run typecheck` — Type-check all packages.
- `pnpm run build` — Type-check and build all packages.
- `pnpm --filter @workspace/api-spec run codegen` — Regenerate API hooks and Zod schemas from the OpenAPI spec.
- `pnpm --filter @workspace/db run push` — Push database schema changes (development only).
- `pnpm --filter @workspace/api-server run dev` — Run the API server locally.

**Environment Variables:**
- `PROPERTYFLOW_URL_PREFIX`: (for `artifacts/propertyflow`) Sets the URL prefix for the app when mounted.
- `PROPERTYFLOW_DB_URL`: (for `artifacts/propertyflow`) Overrides the default SQLite database URL.
- `PROPERTYFLOW_DEV`: (for `artifacts/propertyflow`) Enables development-specific features like test-domain bypass for authentication.
- `SESSION_SECRET`: (for `artifacts/propertyflow`) Required for signed-cookie authentication.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5 (for `api-server`), FastAPI (for Python apps)
- **Database**: PostgreSQL + Drizzle ORM (Node.js), SQLAlchemy with SQLite (Python)
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build tool**: esbuild (CJS bundle)
- **AI**: Ollama (local LLM)

## Where things live

- `pnpm-workspace.yaml`: Defines the monorepo structure.
- `artifacts/property-workflow/`: Marketing site.
    - `docs/`: Deployed output for GitHub Pages.
- `artifacts/workflow-demo/`: Standalone Python FastAPI demo.
    - `data/store.json`: JSON file persistence for the demo.
- `artifacts/propertyflow/`: Multi-tenant FastAPI SaaS application.
    - `app/db.py`: Database setup and session management.
    - `app/models.py`: SQLAlchemy ORM models and schema.
    - `app/auth.py`: Authentication logic.
    - `app/services/ai_service.py`: AI integration for classification and draft generation.
    - `app/services/workflow_service.py`: Core workflow engine.
    - `templates/`: Jinja2 templates.
    - `static/`: Static assets.

## Architecture decisions

- **Multi-tenancy via FKs**: The `propertyflow` app enforces multi-tenancy by including a `tenant_id` foreign key on all operational database rows.
- **Role-based access**: Granular role definitions (`owner`, `admin`, `operator`, `viewer`, `contractor_admin`, `contractor`) are enforced at the API and UI level.
- **Local-first AI with graceful degradation**: The `propertyflow` app uses a local Ollama instance for AI classification and draft generation, silently falling back to deterministic keyword rules if the AI service is unavailable or fails.
- **Prefix-aware FastAPI app**: The `propertyflow` app uses custom middleware to dynamically adjust URLs (`href`, `src`, `action`, `Location` headers) when deployed under a URL prefix, ensuring correct routing without hardcoding paths.
- **Single-use magic links**: Authentication in `propertyflow` uses single-use magic links with nonce rotation to prevent token reuse and enhance security.

## Product

- A marketing website for "Property Workflow Co." showcasing product features.
- A guided, interactive demo of the property workflow system.
- A multi-tenant SaaS application for managing property requests and workflows, featuring:
    - User authentication and role management.
    - Item ingestion, classification, and assignment.
    - AI-powered draft response generation.
    - Task management and status transitions.
    - Multi-company contractor management.
    - Admin and owner dashboards for oversight.

## User preferences

_Populate as you build_

## Gotchas

- **Resend Email Sending**: Until a sending domain is verified with Resend, emails sent to non-test addresses will fail; in dev mode, the magic link will be surfaced inline.
- **Ollama setup**: Ensure Ollama is installed and the `gemma3n:e4b` model is pulled for AI features to function correctly in `propertyflow`. The app will silently fall back to rules-based classification otherwise.

## Pointers

- `pnpm-workspace` skill: For workspace structure, TypeScript setup, and package details.
- [Drizzle ORM Documentation](https://orm.drizzle.team/docs/overview)
- [Zod Documentation](https://zod.dev/)
- [Orval Documentation](https://orval.dev/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Starlette Documentation](https://www.starlette.io/)
- [SQLAlchemy Documentation](https://www.sqlalchemy.org/)
- [Ollama Documentation](https://ollama.com/)
- [Resend API Documentation](https://resend.com/docs)