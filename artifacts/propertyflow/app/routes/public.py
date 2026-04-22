"""Public routes: landing redirect, login, logout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import authenticate_email, current_user, login_user, logout_user, role_home
from app.db import get_db
from app.models import User

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
    user = authenticate_email(db, email)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"No account found for {email!r}. Try one of the demo logins below."},
            status_code=400,
        )
    login_user(request, user)
    return RedirectResponse(role_home(user), status_code=303)


@router.post("/logout")
def logout_post(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)
