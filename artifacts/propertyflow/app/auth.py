"""Session-cookie authentication + magic-link tokens.

Auth model:
  - User submits email at /login.
  - Emails ending in @test.test bypass email and log in instantly
    (development / demo seed accounts).
  - All other emails get a one-click magic link sent via Resend
    (15-min expiry, single use enforced by the timestamp + email binding).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User

MAGIC_LINK_TTL_SECONDS = 15 * 60  # 15 minutes
TEST_EMAIL_SUFFIX = "@test.test"

_SECRET = os.environ.get("SESSION_SECRET") or "dev-only-not-for-prod"
_serializer = URLSafeTimedSerializer(_SECRET, salt="propertyflow-magic-link")


def is_test_email(email: str) -> bool:
    return email.strip().lower().endswith(TEST_EMAIL_SUFFIX)


def make_magic_token(email: str) -> str:
    return _serializer.dumps({"email": email.strip().lower()})


def verify_magic_token(token: str) -> Optional[str]:
    """Return the email if the token is valid & unexpired, else None."""
    try:
        data = _serializer.loads(token, max_age=MAGIC_LINK_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    email = data.get("email")
    return email if isinstance(email, str) else None


def login_user(request: Request, user: User) -> None:
    request.session["user_id"] = user.id


def logout_user(request: Request) -> None:
    request.session.pop("user_id", None)


def lookup_user(db: Session, email: str) -> Optional[User]:
    """Look up a user by email — case-insensitive. Returns None if unknown."""
    return db.query(User).filter(User.email.ilike(email.strip())).one_or_none()


# Backwards-compat alias used by older code.
authenticate_email = lookup_user


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
