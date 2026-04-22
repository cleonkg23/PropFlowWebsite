"""SQLAlchemy engine + session factory.

SQLite lives in ./data/propertyflow.db (alongside the app dir). The dev
default is fine for an MVP — swap engine URL for Postgres later without
touching anything else.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_URL = os.environ.get("PROPERTYFLOW_DB_URL", f"sqlite:///{DATA_DIR / 'propertyflow.db'}")

# check_same_thread=False is required because FastAPI may handle requests
# across threads; we still serialize through SessionLocal per-request.
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# SQLite ships with foreign-key enforcement OFF by default. Without this hook,
# `ondelete=CASCADE` declarations are silently ignored — and SQLite recycles
# deleted row IDs, so orphaned rows would re-attach to whichever new row took
# the freed ID. Turn FKs on for every connection.
if DB_URL.startswith("sqlite"):
    @event.listens_for(Engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model."""


def get_db():
    """FastAPI dependency that yields a request-scoped Session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every boot.

    Also runs a tiny in-place migration for the columns we've added since
    the original schema was created. SQLite doesn't support full migrations
    out of the box; for an MVP an idempotent ADD COLUMN check is enough,
    and lets existing dev databases keep their data through the upgrade.
    """
    # Importing models here registers them on Base.metadata before create_all.
    from app import models  # noqa: F401
    from sqlalchemy import inspect, text

    Base.metadata.create_all(engine)

    # Idempotent column adds for items table.
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("items")}
    additions = [
        ("due_at",          "DATETIME"),
        ("completed_at",    "DATETIME"),
        ("completion_note", "TEXT"),
    ]
    with engine.begin() as conn:
        for name, ddl_type in additions:
            if name not in existing_cols:
                conn.execute(text(f"ALTER TABLE items ADD COLUMN {name} {ddl_type}"))
        # Indexes for the columns we filter on. CREATE INDEX IF NOT EXISTS is
        # safe across reboots and across the case where the table pre-existed
        # before due_at was introduced (create_all only creates indexes for new
        # tables, not for tables it ALTERed via the path above).
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_due_at ON items(due_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_completed_at ON items(completed_at)"))
