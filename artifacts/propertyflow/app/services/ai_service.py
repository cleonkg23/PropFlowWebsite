"""AI service.

Tries Ollama (local Gemma 3n E4B) first, falls back to deterministic rules
if Ollama is unreachable, slow, or returns malformed output. Either way,
the caller gets a usable result and a `mode` string indicating which path ran.

Configuration:
  OLLAMA_HOST   default http://localhost:11434
  OLLAMA_MODEL  default gemma3n:e4b
  OLLAMA_TIMEOUT default 30 (seconds for the HTTP call)

The fallback is intentionally rule-based, not another model — so the demo
never silently hangs on a missing service.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("propertyflow.ai")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "30"))


@dataclass
class Classification:
    category: str
    urgency: str  # low|medium|high
    mode: str    # "ollama" or "fallback"


@dataclass
class Draft:
    text: str
    mode: str


VALID_CATEGORIES = {"maintenance", "viewing", "tenant_enquiry", "landlord_admin", "general"}
VALID_URGENCY = {"low", "medium", "high"}


# --- Fallback rules (also doubles as ground truth for tests) ----------------

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


# --- Ollama path -------------------------------------------------------------

CLASSIFY_PROMPT = """You are an assistant for a UK property management business.
Classify this incoming message. Reply with ONLY a JSON object — no prose, no markdown — using these exact keys:
{{
  "category": one of "maintenance" | "viewing" | "tenant_enquiry" | "landlord_admin" | "general",
  "urgency":  one of "low" | "medium" | "high"
}}

Subject: {subject}
Body: {body}

JSON:"""

DRAFT_PROMPT = """You are a polite, concise UK property manager replying to a message.
Write a short professional reply (3-5 sentences max). Sign off as "{agent}". Do NOT add any preamble like "Here is the reply" — output ONLY the email body.

Original message
  From: {sender}
  Subject: {subject}
  Category (already determined): {category}
  Body: {body}

Reply:"""


_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _ollama_generate(prompt: str) -> Optional[str]:
    """Single non-streaming call. Returns None on any failure."""
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


def _try_parse_classification(raw: str) -> Optional[Classification]:
    # Models sometimes wrap JSON in prose or fences; pull out the first {...}.
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
    return Classification(category=cat, urgency=urg, mode="ollama")


# --- Public API --------------------------------------------------------------


class AIService:
    """Stateless service — safe to use as a module-level singleton."""

    def __init__(self, agent_name: str = "Acme Lettings") -> None:
        self.agent_name = agent_name

    def classify_item(self, subject: str, body: str) -> Classification:
        prompt = CLASSIFY_PROMPT.format(subject=subject[:200], body=body[:1500])
        raw = _ollama_generate(prompt)
        if raw:
            parsed = _try_parse_classification(raw)
            if parsed:
                return parsed
            log.info("ollama classification did not parse: %r", raw[:120])
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
        prompt = DRAFT_PROMPT.format(
            subject=subject[:200],
            body=body[:1500],
            sender=sender_name or "the sender",
            category=category,
            agent=agent,
        )
        raw = _ollama_generate(prompt)
        if raw and len(raw) > 10:
            return Draft(text=raw.strip(), mode="ollama")
        return _fallback_draft(subject, body, category, sender_name, agent)

    def status(self) -> dict[str, str]:
        """Lightweight health probe used by the owner panel.

        Always returns a status dict — never raises. A misbehaving daemon
        (HTTP error, malformed JSON, schema drift) is reported as "down"
        rather than crashing the owner page.
        """
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{OLLAMA_HOST}/api/tags")
                if r.status_code == 200:
                    body = r.json()  # may raise ValueError on malformed body
                    models = body.get("models") or []
                    tags = [m.get("name", "") for m in models if isinstance(m, dict)]
                    has = any(OLLAMA_MODEL.split(":")[0] in t for t in tags)
                    return {
                        "ollama": "up",
                        "model_present": "yes" if has else "no",
                        "model": OLLAMA_MODEL,
                        "host": OLLAMA_HOST,
                    }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.info("ollama status probe failed: %s", e)
        return {"ollama": "down", "model_present": "no", "model": OLLAMA_MODEL, "host": OLLAMA_HOST}


# Module singleton — cheap, stateless.
ai = AIService()
