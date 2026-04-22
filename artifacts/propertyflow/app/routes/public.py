"""Public routes: landing redirect, login, magic-link verify, logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    consume_magic_token,
    current_user,
    is_dev_mode,
    is_test_email,
    login_user,
    logout_user,
    lookup_user,
    make_magic_token,
    role_home,
)
from app.db import get_db
from app.models import User
from app.services.email_service import send_magic_link

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
def index(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(role_home(user), status_code=303)
    return RedirectResponse("/login", status_code=303)


@router.get("/login")
def login_get(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(role_home(user), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_post(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    email_clean = email.strip()
    user = lookup_user(db, email_clean)

    # Generic response on unknown email — render the same "check your inbox"
    # page so we don't leak which addresses are registered. (Test-domain
    # bypass below is only reachable for known users by design.)
    if not user:
        if is_test_email(email_clean):
            # Test domain + unknown user is genuinely "no account" — surface it
            # since this branch only runs in dev mode.
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": f"No account found for {email_clean!r}."},
                status_code=400,
            )
        return templates.TemplateResponse(
            request,
            "login_sent.html",
            {"email": email_clean, "delivered": True, "fallback_url": None},
        )

    # Test-domain shortcut (dev only): instant login, no email sent.
    if is_test_email(email_clean):
        login_user(request, user)
        return RedirectResponse(role_home(user), status_code=303)

    # Real email: send magic link.
    token = make_magic_token(user)
    magic_url = str(request.url_for("login_verify").include_query_params(token=token))
    delivered = send_magic_link(email_clean, magic_url)

    # Only expose the raw magic URL inline when in dev mode — otherwise it
    # would be an auth bypass for any actor who knows a valid email during
    # an email-delivery outage.
    fallback_url = magic_url if (not delivered and is_dev_mode()) else None

    return templates.TemplateResponse(
        request,
        "login_sent.html",
        {"email": email_clean, "delivered": delivered, "fallback_url": fallback_url},
    )


@router.get("/login/verify", name="login_verify")
def login_verify(request: Request, token: str, db: Session = Depends(get_db)):
    user = consume_magic_token(db, token)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That sign-in link is invalid, expired, or has already been used. Request a new one."},
            status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(role_home(user), status_code=303)


@router.post("/logout")
def logout_post(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
