"""IMAP/Gmail email connector — stub. See google_sheets.py for the pattern."""
from __future__ import annotations

from typing import Iterable

from app.services.connectors.base import IngestPayload


class EmailInboxConnector:
    name = "email_inbox"

    def __init__(self, mailbox: str | None = None) -> None:
        self.mailbox = mailbox

    def fetch_new(self) -> Iterable[IngestPayload]:
        return []
