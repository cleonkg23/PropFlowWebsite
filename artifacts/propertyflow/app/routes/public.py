"""Public routes: landing redirect, login, magic-link verify, logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    current_user,
    is_test_email,
    login_user,
    logout_user,
    lookup_user,
    make_magic_token,
    role_home,
    verify_magic_token,
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
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"No account found for {email_clean!r}. Ask your admin to add you."},
            status_code=400,
        )

    # Test-domain shortcut: instant login, no email sent.
    if is_test_email(email_clean):
        login_user(request, user)
        return RedirectResponse(role_home(user), status_code=303)

    # Real email: send magic link.
    token = make_magic_token(email_clean)
    magic_url = str(request.url_for("login_verify").include_query_params(token=token))
    delivered = send_magic_link(email_clean, magic_url)

    return templates.TemplateResponse(
        request,
        "login_sent.html",
        {"email": email_clean, "delivered": delivered, "fallback_url": magic_url if not delivered else None},
    )


@router.get("/login/verify", name="login_verify")
def login_verify(request: Request, token: str, db: Session = Depends(get_db)):
    email = verify_magic_token(token)
    if not email:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That sign-in link is invalid or has expired. Request a new one."},
            status_code=400,
        )
    user = lookup_user(db, email)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That account no longer exists."},
            status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(role_home(user), status_code=303)


@router.post("/logout")
def logout_post(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
