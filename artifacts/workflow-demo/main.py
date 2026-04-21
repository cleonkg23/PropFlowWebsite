"""FastAPI entrypoint.

Layers:
  Input layer  -> POST /ingest, POST /demo/{key}
  Processing   -> workflow.ingest()
  Storage      -> store.py (JSON file)
  UI layer     -> GET /  (Jinja2 + Tailwind CDN, polls /api/state)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scenarios import SCENARIOS
from store import get_state, reset
from workflow import ingest, update_status

ROOT = Path(__file__).parent
app = FastAPI(title="Property Workflow Demo")

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"scenarios": SCENARIOS}
    )


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    return get_state()


@app.post("/api/reset")
def api_reset() -> dict[str, str]:
    reset()
    return {"status": "ok"}


@app.post("/ingest")
async def api_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("message"):
        raise HTTPException(400, "message is required")
    return ingest(payload)


@app.post("/api/items/{item_id}/status")
def api_status(item_id: str, body: dict[str, Any]) -> dict[str, Any]:
    to_status = body.get("status")
    if not to_status:
        raise HTTPException(400, "status is required")
    try:
        return update_status(item_id, to_status)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/demo/{key}")
def api_demo(key: str) -> dict[str, Any]:
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise HTTPException(404, f"unknown scenario: {key}")
    return ingest(scenario)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
