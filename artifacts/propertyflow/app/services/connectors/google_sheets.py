"""Google Sheets connector — stub.

Real implementation would: poll a sheet via the Sheets API, treat each new
row as a payload, and stash the last-seen row index in a small KV table.
For the MVP we just declare the surface so wiring it later is a contained
change.
"""
from __future__ import annotations

from typing import Iterable

from app.services.connectors.base import IngestPayload


class GoogleSheetsConnector:
    name = "google_sheets"

    def __init__(self, spreadsheet_id: str | None = None) -> None:
        self.spreadsheet_id = spreadsheet_id

    def fetch_new(self) -> Iterable[IngestPayload]:
        # Not implemented for MVP — see module docstring.
        return []
