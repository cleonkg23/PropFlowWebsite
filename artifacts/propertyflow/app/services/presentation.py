"""View-layer helpers — pure functions used by Jinja templates to keep
display logic out of the route handlers and out of the templates themselves.

Nothing here touches the DB; callers pass in plain models / strings.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote_plus


# Subject lines look like:
#   "Boiler out at 14 Park Road"
#   "Re: viewing at 22 Elm"
#   "Window stuck at 8 Birch — Flat 2"
# Take everything after the LAST " at " (case-insensitive) and trim trailing
# punctuation / quoted suffixes. Best-effort — if we can't find one we just
# return None and the UI hides the maps link entirely. Production setups
# should override with whatever address comes from their CRM/PM data.
_AT_SPLIT = re.compile(r"\s+at\s+", re.IGNORECASE)


def extract_address(subject: str | None) -> Optional[str]:
    if not subject:
        return None
    parts = _AT_SPLIT.split(subject.strip())
    if len(parts) < 2:
        return None
    candidate = parts[-1].strip(" .,;:—-\"'")
    # Reject results that don't look like an address — must contain a digit
    # (street number or postcode) so we don't pull "the contractor" out of
    # something like "Spoke at the contractor".
    if not any(ch.isdigit() for ch in candidate):
        return None
    # Cap length so a long subject doesn't bleed everything into the chip.
    return candidate[:80]


def maps_url_for(address: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}"


# --- Task description splitter -----------------------------------------
# Many task descriptions follow the pattern "<title>. Done when: <criteria>".
# Splitting them lets templates render the title prominently and the
# acceptance criteria as a quieter second line.
_DONE_WHEN = re.compile(r"\.\s*Done when:\s*", re.IGNORECASE)


def split_task_desc(description: str) -> tuple[str, str]:
    """Return (title, done_when). done_when is "" if no marker present."""
    if not description:
        return "", ""
    parts = _DONE_WHEN.split(description, maxsplit=1)
    if len(parts) == 2:
        title, criteria = parts
        return title.strip(), criteria.strip().rstrip(".")
    return description.strip(), ""


# --- Timeline humanizer -------------------------------------------------
# Turns the audit-log raw `action` + `detail` strings into something a
# non-technical user can read. We DON'T discard information — anything we
# can't pretty up gets passed through as-is.

_ACTION_LABEL = {
    "ingest": "Ticket received",
    "status_change": "Status changed",
    "assign": "Item reassigned",
    "edit_draft": "Draft updated",
    "send_reply": "Reply sent",
    "task_complete": "Task complete",
    "task_created": "Task created",
    "acknowledge": "Acknowledged",
    "complete": "Item closed",
    "note": "Note",
    "auto_close": "Ticket auto-closed",
    "reopen": "Ticket reopened",
    "task_assign": "Task reassigned",
    "task_postpone": "Task postponed",
    "task_handback": "Task handed back",
    "regenerate_draft": "Draft regenerated",
}

_STATUS_PRETTY = {
    "new": "New",
    "acknowledged": "Acknowledged",
    "in_progress": "In progress",
    "awaiting_reply": "Awaiting reply",
    "done": "Done",
}


def _pretty_status_arrow(detail: str) -> str:
    """Rewrite "in_progress -> awaiting_reply" → "In progress → Awaiting reply"."""
    if "->" not in detail:
        return detail
    left, _, right = detail.partition("->")
    left, right = left.strip(), right.strip()
    return f"{_STATUS_PRETTY.get(left, left)} → {_STATUS_PRETTY.get(right, right)}"


def humanize_event(action: str, detail: str | None) -> tuple[str, str]:
    """Return (label, detail) — both already display-ready."""
    label = _ACTION_LABEL.get(action, action.replace("_", " ").capitalize())
    detail = (detail or "").strip()

    if action == "ingest":
        # raw: "category=maintenance urgency=high mode=openrouter"
        parts = dict(
            piece.split("=", 1) for piece in detail.split() if "=" in piece
        )
        cat = parts.get("category", "").replace("_", " ")
        urg = parts.get("urgency", "")
        mode = parts.get("mode", "")
        bits: list[str] = []
        if cat:
            bits.append(cat.capitalize())
        if urg:
            bits.append(f"{urg} urgency")
        if mode and mode != "openrouter":
            bits.append(f"classified by {mode}")
        elif mode == "openrouter":
            bits.append("classified by AI")
        return label, " · ".join(bits) or detail

    if action == "edit_draft":
        m = re.match(r"len=(\d+)", detail)
        if m:
            n = int(m.group(1))
            return label, f"reply now {n} character{'s' if n != 1 else ''} long"
        return label, detail

    if action in {"status_change", "send_reply", "acknowledge", "auto_close", "complete"}:
        # Auto_close detail: "in_progress -> done (last task complete)"
        # Pretty-up the arrow but keep any trailing parenthetical.
        if "->" in detail:
            head, _, tail = detail.partition("(")
            arrow = _pretty_status_arrow(head.strip())
            if tail:
                return label, f"{arrow} ({tail.strip()}"
            return label, arrow
        return label, detail

    if action == "task_created":
        # raw: "handoff -> Mike Dispatch (contractor admin): On-site visit ..."
        if detail.startswith("handoff -> "):
            rest = detail[len("handoff -> "):]
            assignee, _, desc = rest.partition(": ")
            title, _criteria = split_task_desc(desc)
            return label, f"dispatched to {assignee} — {title}"
        return label, detail

    if action == "task_complete":
        # raw: "<truncated description> — auto-closed on reply" or with note
        # Keep as-is; the description and note are already human.
        return label, detail

    if action == "task_assign":
        # raw: "<desc> — user_id 5 -> 6"  → strip the user_id mechanics
        m = re.match(r"(.*?)\s*—\s*user_id\s+\S+\s*->\s*\S+\s*$", detail)
        if m:
            return label, m.group(1).strip()
        return label, detail

    if action == "regenerate_draft":
        m = re.match(r"mode=(\w+)", detail)
        if m:
            mode = m.group(1)
            if mode == "openrouter":
                return label, "regenerated by AI"
            return label, f"regenerated by {mode}"
        return label, detail

    if action == "assign":
        # raw: "-> user_id=12"  → not very useful; just say "ownership changed"
        return label, ""

    return label, detail
