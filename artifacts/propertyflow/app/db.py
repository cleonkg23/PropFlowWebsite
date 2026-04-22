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

    # Migration guard: SQLite emits a CHECK constraint listing the enum values
    # at table-creation time. When we add a new Role value (e.g. "contractor"),
    # existing tables still carry the old constraint and will reject inserts
    # of the new value. Detect that case and rebuild the users table from
    # scratch — for an MVP with seed-only data this is acceptable; a real
    # production migration would copy the rows out and back.
    inspector = inspect(engine)
    rebuild = False
    if inspector.has_table("users"):
        from app.models import Role
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (tenant_id, email, name, role, auth_nonce) "
                    "VALUES (NULL, '__schemacheck__@local', 'check', :r, 'x')"
                ), {"r": Role.contractor_admin.value})
                conn.execute(text("DELETE FROM users WHERE email = '__schemacheck__@local'"))
        except Exception:  # noqa: BLE001
            rebuild = True

    # Schema marker: if the old schema doesn't have the contractor_companies
    # table, the multi-company contractor model isn't in place — easiest path
    # for a demo MVP is to rebuild and reseed (no real production data yet).
    if inspector.has_table("users") and not inspector.has_table("contractor_companies"):
        rebuild = True

    if rebuild:
        import logging
        logging.getLogger("propertyflow").info(
            "Schema changed; rebuilding (existing rows will be reseeded)."
        )
        Base.metadata.drop_all(engine)

    Base.metadata.create_all(engine)

    # Idempotent column adds for tables that may pre-date current columns.
    # Safe across reboots; create_all only creates new tables, never ALTERs.
    inspector = inspect(engine)
    with engine.begin() as conn:
        item_cols = {c["name"] for c in inspector.get_columns("items")}
        for name, ddl_type in [
            ("due_at",          "DATETIME"),
            ("completed_at",    "DATETIME"),
            ("completion_note", "TEXT"),
            ("contractor_company_id", "INTEGER"),
        ]:
            if name not in item_cols:
                conn.execute(text(f"ALTER TABLE items ADD COLUMN {name} {ddl_type}"))
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        if "contractor_company_id" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN contractor_company_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_due_at ON items(due_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_completed_at ON items(completed_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_contractor_company_id ON items(contractor_company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_contractor_company_id ON users(contractor_company_id)"))
