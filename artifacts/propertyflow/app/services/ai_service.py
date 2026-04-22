"""AI service.

Priority order:
  1. OpenRouter (Gemma 4 via Replit AI Integrations proxy) — primary
  2. Ollama (local Gemma 3n E4B) — for local development
  3. Deterministic rule-based fallback — always works, never hangs

Configuration (all optional — defaults make sense for each environment):
  AI_INTEGRATIONS_OPENROUTER_BASE_URL   set by Replit AI Integrations
  AI_INTEGRATIONS_OPENROUTER_API_KEY    set by Replit AI Integrations
  OPENROUTER_MODEL                      default google/gemma-4-31b-it
  OLLAMA_HOST                           default http://localhost:11434
  OLLAMA_MODEL                          default gemma3n:e4b
  OLLAMA_TIMEOUT                        default 30 seconds
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("propertyflow.ai")

# --- OpenRouter (primary) ----------------------------------------------------
OPENROUTER_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENROUTER_BASE_URL", "").rstrip("/")
OPENROUTER_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it")
OPENROUTER_TIMEOUT = float(os.environ.get("OPENROUTER_TIMEOUT", "30"))

# --- Ollama (local dev fallback) ---------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "30"))


@dataclass
class Classification:
    category: str
    urgency: str   # low | medium | high
    mode: str      # "openrouter" | "ollama" | "fallback"


@dataclass
class Draft:
    text: str
    mode: str      # "openrouter" | "ollama" | "fallback"


VALID_CATEGORIES = {"maintenance", "viewing", "tenant_enquiry", "landlord_admin", "general"}
VALID_URGENCY = {"low", "medium", "high"}


# --- Deterministic fallback rules -------------------------------------------

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "maintenance": ("boiler", "leak", "broken", "repair", "heating", "no hot water", "damp", "fault", "fix"),
    "viewing": ("viewing", "view the", "second viewing", "appointment", "showing", "tour"),
    "tenant_enquiry": ("available", "rent", "deposit", "move in", "tenancy", "application"),
    "landlord_admin": ("statement", "invoice", "renewal", "landlord", "remit", "compliance", "gas safety", "certificate"),
}
URGENT_TOKENS = ("urgent", "asap", "emergency", "no hot water", "leak", "no heat")
HIGH_TOKENS = ("today", "tomorrow", "chase", "second time", "still waiting", "chasing")


def _fallback_classify(subject: str, body: str) -> Classification:
    text = f"{subject}\n{body}".lower()
    category = "general"
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            category = cat
            break
    if any(t in text for t in URGENT_TOKENS):
        urgency = "high"
    elif any(t in text for t in HIGH_TOKENS):
        urgency = "high"
    else:
        urgency = "medium"
    return Classification(category=category, urgency=urgency, mode="fallback")


_DRAFT_TEMPLATES = {
    "maintenance": "Hi {name},\n\nThanks for letting us know — sorry you're dealing with this. I've logged it as {urgency} priority and a contractor will be in touch shortly to arrange access.\n\nBest,\n{agent}",
    "viewing": "Hi {name},\n\nThanks for getting in touch about the viewing. I can offer a couple of slots this week — happy to confirm whichever works.\n\nBest,\n{agent}",
    "tenant_enquiry": "Hi {name},\n\nThanks for the message. The property is available — I can share full details and arrange a viewing if you'd like to take it forward.\n\nBest,\n{agent}",
    "landlord_admin": "Hi {name},\n\nThanks — I'll pull the figures and the outstanding items together and come back to you shortly.\n\nBest,\n{agent}",
    "general": "Hi {name},\n\nThanks for getting in touch — I'll review and come back to you shortly.\n\nBest,\n{agent}",
}


def _fallback_draft(subject: str, body: str, category: str, sender_name: Optional[str], agent_name: str) -> Draft:
    template = _DRAFT_TEMPLATES.get(category, _DRAFT_TEMPLATES["general"])
    name = (sender_name or "there").split()[0]
    urgency = "high" if any(t in body.lower() for t in URGENT_TOKENS) else "normal"
    return Draft(text=template.format(name=name, urgency=urgency, agent=agent_name), mode="fallback")


# --- OpenRouter path (primary) ----------------------------------------------

def _openrouter_chat(messages: list[dict]) -> Optional[str]:
    """Call OpenRouter chat completions. Returns the assistant content or None."""
    if not OPENROUTER_BASE_URL or not OPENROUTER_API_KEY:
        return None
    try:
        with httpx.Client(timeout=OPENROUTER_TIMEOUT) as client:
            r = client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 512,
                },
            )
            r.raise_for_status()
            data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        log.warning("openrouter chat failed: %s", e)
        return None


# --- Ollama path (local dev) -------------------------------------------------

def _ollama_generate(prompt: str) -> Optional[str]:
    """Non-streaming Ollama call. Returns None on any failure."""
    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
            r = client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("ollama generate failed: %s", e)
        return None


# --- JSON parse helpers -----------------------------------------------------

_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _try_parse_classification(raw: str, mode: str) -> Optional[Classification]:
    match = _JSON_RE.search(raw)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    cat = str(obj.get("category", "")).strip().lower()
    urg = str(obj.get("urgency", "")).strip().lower()
    if cat not in VALID_CATEGORIES or urg not in VALID_URGENCY:
        return None
    return Classification(category=cat, urgency=urg, mode=mode)


# --- Prompts ----------------------------------------------------------------

CLASSIFY_SYSTEM = "You are an assistant for a UK property management business. Classify the incoming message and reply with ONLY a valid JSON object — no prose, no markdown fences."
CLASSIFY_USER = """Classify this message. Reply with ONLY this JSON structure:
{{"category": "<one of: maintenance|viewing|tenant_enquiry|landlord_admin|general>", "urgency": "<one of: low|medium|high>"}}

Subject: {subject}
Body: {body}

JSON:"""

DRAFT_SYSTEM = "You are a polite, concise UK property manager. Write professional, warm email replies. Output ONLY the email body — no subject line, no preamble like 'Here is the reply'."
DRAFT_USER = """Reply to this message. Keep it to 3-5 sentences. Sign off as "{agent}".

From: {sender}
Subject: {subject}
Category: {category}
Body: {body}

Reply:"""


# --- Public API -------------------------------------------------------------

_STATUS_TTL = 60  # seconds between live status probes


class AIService:
    """Stateless singleton — tries OpenRouter first, then Ollama, then rules."""

    def __init__(self, agent_name: str = "Acme Lettings") -> None:
        self.agent_name = agent_name
        self._status_cache: Optional[dict] = None
        self._status_at: float = 0

    def classify_item(self, subject: str, body: str) -> Classification:
        # 1. OpenRouter (Gemma 4)
        msgs = [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": CLASSIFY_USER.format(subject=subject[:300], body=body[:2000])},
        ]
        raw = _openrouter_chat(msgs)
        if raw:
            parsed = _try_parse_classification(raw, "openrouter")
            if parsed:
                log.info("classified via openrouter: %s %s", parsed.category, parsed.urgency)
                return parsed
            log.info("openrouter classification did not parse: %r", raw[:120])

        # 2. Ollama (local dev)
        if not OPENROUTER_BASE_URL:
            prompt = f"{CLASSIFY_SYSTEM}\n\n{CLASSIFY_USER.format(subject=subject[:300], body=body[:2000])}"
            raw = _ollama_generate(prompt)
            if raw:
                parsed = _try_parse_classification(raw, "ollama")
                if parsed:
                    return parsed

        # 3. Rules
        return _fallback_classify(subject, body)

    def generate_draft(
        self,
        subject: str,
        body: str,
        category: str,
        sender_name: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> Draft:
        agent = agent_name or self.agent_name

        # 1. OpenRouter (Gemma 4)
        msgs = [
            {"role": "system", "content": DRAFT_SYSTEM},
            {"role": "user", "content": DRAFT_USER.format(
                subject=subject[:300],
                body=body[:2000],
                sender=sender_name or "the sender",
                category=category,
                agent=agent,
            )},
        ]
        raw = _openrouter_chat(msgs)
        if raw and len(raw) > 15:
            log.info("draft generated via openrouter, len=%d", len(raw))
            return Draft(text=raw.strip(), mode="openrouter")

        # 2. Ollama (local dev)
        if not OPENROUTER_BASE_URL:
            prompt_text = DRAFT_USER.format(
                subject=subject[:300], body=body[:2000],
                sender=sender_name or "the sender", category=category, agent=agent,
            )
            raw = _ollama_generate(f"{DRAFT_SYSTEM}\n\n{prompt_text}")
            if raw and len(raw) > 10:
                return Draft(text=raw.strip(), mode="ollama")

        # 3. Rules
        return _fallback_draft(subject, body, category, sender_name, agent)

    def status(self) -> dict[str, str]:
        """Health probe for the owner panel. Cached for _STATUS_TTL seconds."""
        now = time.monotonic()
        if self._status_cache and (now - self._status_at) < _STATUS_TTL:
            return self._status_cache

        result = self._probe_status()
        self._status_cache = result
        self._status_at = now
        return result

    def _probe_status(self) -> dict[str, str]:
        """Internal — performs lightweight network probes.

        OpenRouter: env vars being set means Replit has provisioned the
        integration. We verify the proxy host is reachable (TCP connect)
        rather than doing a full chat completion, so the owner page stays fast.
        """
        # Check OpenRouter — if env vars are provisioned, trust the integration
        if OPENROUTER_BASE_URL and OPENROUTER_API_KEY:
            try:
                # Parse out host/port from the proxy URL for a quick check
                import urllib.parse
                parsed = urllib.parse.urlparse(OPENROUTER_BASE_URL)
                host = parsed.hostname or "localhost"
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                import socket
                sock = socket.create_connection((host, port), timeout=3.0)
                sock.close()
                return {
                    "engine": "openrouter",
                    "ollama": "n/a",
                    "model": OPENROUTER_MODEL,
                    "model_present": "yes",
                    "host": OPENROUTER_BASE_URL,
                }
            except OSError as e:
                log.info("openrouter proxy not reachable: %s", e)

        # Check Ollama
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{OLLAMA_HOST}/api/tags")
                if r.status_code == 200:
                    body = r.json()
                    models = body.get("models") or []
                    tags = [m.get("name", "") for m in models if isinstance(m, dict)]
                    has = any(OLLAMA_MODEL.split(":")[0] in t for t in tags)
                    return {
                        "engine": "ollama",
                        "ollama": "up",
                        "model": OLLAMA_MODEL,
                        "model_present": "yes" if has else "no",
                        "host": OLLAMA_HOST,
                    }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.info("ollama status probe failed: %s", e)

        return {
            "engine": "fallback",
            "ollama": "down",
            "model": "rule-based",
            "model_present": "no",
            "host": "",
        }


# Module singleton — cheap, stateless.
ai = AIService()
