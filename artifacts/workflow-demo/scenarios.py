"""Pre-baked demo payloads — one per required scenario.

Scenarios deliberately omit `type` so the keyword classifier in
workflow.classify_input does the work — that's the point of the demo.

PRESSURE_ITEMS are seed messages that pre-populate the inbox so the demo
feels operationally real (chasers, urgent, etc.) rather than starting empty.
They go through the full pipeline like any other ingest.
"""

SCENARIOS = {
    "tenant_enquiry": {
        "label": "Tenant enquiry",
        "from_name": "Aisha Khan",
        "property": "Flat 3B, 14 Park Road",
        "message": (
            "Hi, is Flat 3B on Park Road still available to rent? Could you let "
            "me know the deposit and when I could move in?"
        ),
    },
    "maintenance": {
        "label": "Maintenance request",
        "from_name": "Mr Patel (14 Park Rd)",
        "property": "14 Park Road",
        "message": (
            "URGENT — boiler is out, no hot water since last night. Two kids in the "
            "flat, please can someone come today."
        ),
    },
    "viewing": {
        "label": "Viewing follow-up",
        "from_name": "James Wright",
        "property": "22 Elm Avenue",
        "message": (
            "Thanks for the viewing at 22 Elm yesterday — really liked it. Could "
            "we book a second viewing this week?"
        ),
    },
    "landlord_admin": {
        "label": "Landlord admin request",
        "from_name": "Mrs Holloway (landlord)",
        "property": "Portfolio (3 properties)",
        "message": (
            "Could I get the Q4 landlord statement for the three properties, plus "
            "a note on the gas safety renewal that was due last month?"
        ),
    },
}

# Inbox-pressure messages: realistic chasers that sit in the inbox so the
# demo doesn't start from an empty slate. Loaded once on first page view.
PRESSURE_ITEMS = [
    {
        "from_name": "Lauren (8 Beech Cl.)",
        "property": "8 Beech Close",
        "message": "Still waiting — any update on the kitchen tap repair? It's been four days.",
    },
    {
        "from_name": "Daniel Brooks",
        "property": "12 Sycamore Way",
        "message": "Chasing on the deposit return — second time asking, can someone pick this up please?",
    },
]
