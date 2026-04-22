"""SQLAlchemy ORM models for PropertyFlow.

Multi-tenant by `tenant_id` foreign key on every operational row. The
system `owner` user has `tenant_id = NULL` and crosses tenant boundaries.
"""
from __future__ import annotations

import enum
import secrets as _secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


def _new_nonce() -> str:
    """Per-user random nonce; rotated on every successful magic-link login
    to enforce single-use semantics on outstanding tokens."""
    return _secrets.token_urlsafe(16)


class Role(str, enum.Enum):
    owner = "owner"      # system-level (no tenant or any tenant)
    admin = "admin"      # tenant manager
    operator = "operator"  # day-to-day staff
    viewer = "viewer"    # read-only

    @property
    def rank(self) -> int:
        return {"viewer": 1, "operator": 2, "admin": 3, "owner": 4}[self.value]


class ItemStatus(str, enum.Enum):
    new = "new"
    acknowledged = "acknowledged"   # recipient told we've received it
    in_progress = "in_progress"
    awaiting_reply = "awaiting_reply"
    done = "done"


class Urgency(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskStatus(str, enum.Enum):
    open = "open"
    done = "done"


# ---------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    items: Mapped[list["Item"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.operator)
    # Rotated on every successful magic-link sign-in. Embedded in magic-link
    # tokens; verifying a token requires the nonce still match the user row.
    auth_nonce: Mapped[str] = mapped_column(String(32), default=_new_nonce)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    tenant: Mapped[Optional[Tenant]] = relationship(back_populates="users")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)

    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    sender_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sender_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    category: Mapped[str] = mapped_column(String(64), default="general")
    urgency: Mapped[Urgency] = mapped_column(Enum(Urgency), default=Urgency.medium)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.new, index=True)

    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    draft_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # "ollama" or "fallback"

    # Operational metadata: due/SLA target on the item itself (mirrors the
    # primary task's due_at, but lets the dashboard age items without joining)
    # and completion proof captured when the item is closed.
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completion_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="items")
    assigned_user: Mapped[Optional[User]] = relationship(foreign_keys=[assigned_user_id])
    tasks: Mapped[list["Task"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)

    description: Mapped[str] = mapped_column(String(255))
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    item: Mapped[Item] = relationship(back_populates="tasks")
    assigned_user: Mapped[Optional[User]] = relationship(foreign_keys=[assigned_user_id])


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
