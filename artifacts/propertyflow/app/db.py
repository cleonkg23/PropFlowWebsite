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
    """Create all tables. Idempotent — safe to call on every boot."""
    # Importing models here registers them on Base.metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
