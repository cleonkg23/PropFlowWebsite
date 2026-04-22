"""Resend transactional email — credentials fetched from the Replit
connector API on every send (tokens may rotate; never cache).

Falls back to logging the email to stdout if the connector is unreachable
or the API call fails, so dev never gets blocked.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
import resend

log = logging.getLogger("propertyflow.email")


def _get_credentials() -> Optional[dict]:
    hostname = os.environ.get("REPLIT_CONNECTORS_HOSTNAME")
    repl_identity = os.environ.get("REPL_IDENTITY")
    web_renewal = os.environ.get("WEB_REPL_RENEWAL")

    if repl_identity:
        token = f"repl {repl_identity}"
    elif web_renewal:
        token = f"depl {web_renewal}"
    else:
        log.warning("No REPL_IDENTITY / WEB_REPL_RENEWAL — cannot fetch Resend creds")
        return None
    if not hostname:
        log.warning("REPLIT_CONNECTORS_HOSTNAME not set")
        return None

    try:
        r = httpx.get(
            f"https://{hostname}/api/v2/connection",
            params={"include_secrets": "true", "connector_names": "resend"},
            headers={"Accept": "application/json", "X-Replit-Token": token},
            timeout=8.0,
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            log.warning("Resend connection not found")
            return None
        settings = items[0].get("settings") or {}
        api_key = settings.get("api_key")
        if not api_key:
            log.warning("Resend api_key missing in connection settings")
            return None
        from_email = settings.get("from_email") or "onboarding@resend.dev"
        return {"api_key": api_key, "from_email": from_email}
    except Exception as e:
        log.warning("Failed to fetch Resend credentials: %s", e)
        return None


def send_magic_link(to_email: str, magic_url: str) -> bool:
    """Send a sign-in magic link. Returns True on apparent success.

    On failure, logs the magic URL to stdout so the operator can copy it
    manually — the system never silently strands a user.
    """
    creds = _get_credentials()
    if not creds:
        log.error("EMAIL FALLBACK — magic link for %s: %s", to_email, magic_url)
        return False

    resend.api_key = creds["api_key"]
    subject = "Your PropertyFlow sign-in link"
    html = f"""\
<div style="font-family: -apple-system, system-ui, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px 24px; color: #1a1a1a;">
  <p style="font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; color: #8a6a3a; margin: 0 0 8px;">§ Property Workflow Co.</p>
  <h1 style="font-family: Georgia, serif; font-size: 26px; margin: 0 0 16px; line-height: 1.2;">Sign in to PropertyFlow</h1>
  <p style="font-size: 15px; line-height: 1.55; color: #444; margin: 0 0 24px;">
    Click the button below to sign in. This link expires in 15 minutes and can only be used once.
  </p>
  <p style="margin: 0 0 24px;">
    <a href="{magic_url}" style="display: inline-block; background: #1a1a1a; color: #fff; text-decoration: none; padding: 12px 22px; font-size: 14px; font-weight: 600; border-radius: 4px;">Sign in →</a>
  </p>
  <p style="font-size: 13px; color: #777; line-height: 1.5; margin: 0 0 8px;">
    Or paste this URL into your browser:
  </p>
  <p style="font-size: 12px; color: #999; word-break: break-all; font-family: 'SF Mono', Menlo, monospace; margin: 0 0 32px;">{magic_url}</p>
  <p style="font-size: 12px; color: #999; border-top: 1px solid #eee; padding-top: 16px; margin: 0;">
    If you didn't request this, you can safely ignore this email.
  </p>
</div>"""

    try:
        resend.Emails.send({
            "from": creds["from_email"],
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        log.info("Sent magic link to %s", to_email)
        return True
    except Exception as e:
        log.error("Resend send failed for %s: %s — link: %s", to_email, e, magic_url)
        return False
