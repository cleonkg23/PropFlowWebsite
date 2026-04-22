"""Session-cookie authentication.

Dev model (per spec — "no passwords, magic link OR simple login"):
  - User submits email at /login
  - If email matches a seeded user, set session.user_id and redirect by role
  - No magic-link email is actually sent — for an MVP demo we trust the form

This is intentionally simple. Replace the body of `authenticate_email` with
a real magic-link flow (sign a token, email it, accept it at /login/magic)
when moving past MVP.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User


def login_user(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def logout_user(request: Request) -> None:
    request.session.pop("user_id", None)


def authenticate_email(db: Session, email: str) -> Optional[User]:
    """Look up a user by email — case-insensitive. Returns None if unknown."""
    return db.query(User).filter(User.email.ilike(email.strip())).one_or_none()


def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Optional dependency — None for anonymous requests."""
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, uid)


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    """Dependency that enforces login (raises 401 if anonymous)."""
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return user


def require_role(*allowed: Role):
    """Dependency factory: only allow users whose role is in `allowed`.

    Owner role passes every check (system-level)."""
    allowed_set = set(allowed)

    def _checker(user: User = Depends(require_user)) -> User:
        if user.role is Role.owner or user.role in allowed_set:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")

    return _checker


def role_home(user: User) -> str:
    """Where to send a user after login."""
    if user.role is Role.owner:
        return "/owner"
    if user.role is Role.admin:
        return "/admin"
    return "/dashboard"
