"""Tiny JSON-file store. Single source of truth for items and tasks.

Kept intentionally minimal: load on read, write on mutation.
Replace with SQLite or a real DB later without touching workflow.py.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
STORE_FILE = DATA_DIR / "store.json"

_lock = threading.RLock()  # reentrant so seed_if_empty() can wrap multiple ingest calls
_EMPTY: dict[str, list[dict[str, Any]]] = {"items": [], "tasks": []}


def _ensure() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not STORE_FILE.exists():
        STORE_FILE.write_text(json.dumps(_EMPTY, indent=2))


def _read() -> dict[str, list[dict[str, Any]]]:
    _ensure()
    try:
        return json.loads(STORE_FILE.read_text())
    except json.JSONDecodeError:
        return {"items": [], "tasks": []}


def _write(state: dict[str, list[dict[str, Any]]]) -> None:
    _ensure()
    tmp = STORE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STORE_FILE)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def add_item(item: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        state = _read()
        state["items"].append(item)
        _write(state)
    return item


def add_task(task: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        state = _read()
        state["tasks"].append(task)
        _write(state)
    return task


def update_item(item_id: str, **changes: Any) -> dict[str, Any] | None:
    with _lock:
        state = _read()
        for it in state["items"]:
            if it["id"] == item_id:
                it.update(changes)
                _write(state)
                return it
        return None


def get_state() -> dict[str, list[dict[str, Any]]]:
    return _read()


def reset() -> None:
    with _lock:
        _write({"items": [], "tasks": []})
