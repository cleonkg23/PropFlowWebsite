"""FastAPI app entrypoint for PropertyFlow."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.db import SessionLocal, init_db
from app.routes import admin, api, dashboard, owner, public
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("propertyflow")

ROOT = Path(__file__).resolve().parent.parent  # artifacts/propertyflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
    log.info("propertyflow ready (db=%s)", os.environ.get("PROPERTYFLOW_DB_URL", "sqlite default"))
    yield


app = FastAPI(title="PropertyFlow", lifespan=lifespan)

# Session middleware — signed cookie.
# SESSION_SECRET MUST be set; we only allow a generated dev fallback when
# PROPERTYFLOW_DEV=1 is explicitly set, so a misconfigured production deploy
# cannot silently accept forged cookies.
_session_secret = os.environ.get("SESSION_SECRET")
if not _session_secret:
    if os.environ.get("PROPERTYFLOW_DEV") == "1":
        import secrets as _secrets
        _session_secret = _secrets.token_urlsafe(48)
        # Write back so auth.py (and any other consumer) sees the same secret.
        os.environ["SESSION_SECRET"] = _session_secret
        log.warning("SESSION_SECRET not set — using ephemeral dev secret (PROPERTYFLOW_DEV=1)")
    else:
        raise RuntimeError(
            "SESSION_SECRET is required. Set it in the environment, or set PROPERTYFLOW_DEV=1 "
            "to allow an ephemeral dev secret."
        )

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    same_site="lax",
    https_only=False,  # dev preview is proxied; cookie must work over http
)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

app.include_router(public.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(owner.router)
app.include_router(api.router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8002"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
