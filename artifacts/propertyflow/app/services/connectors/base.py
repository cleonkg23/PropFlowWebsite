"""Connector adapter interface.

Each connector converts an *external source* into the internal `Item` shape
that workflow_service.ingest_item() expects. Implementations are stubs for
the MVP — the contract is what matters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Protocol


@dataclass
class IngestPayload:
    subject: str
    body: str
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    external_id: Optional[str] = None  # e.g. gmail message id, sheet row id


class Connector(Protocol):
    """Source → IngestPayload adapter."""

    name: str

    def fetch_new(self) -> Iterable[IngestPayload]:
        """Yield payloads not previously ingested. Implementations are
        responsible for tracking their own checkpoint (sheet row cursor,
        gmail history id, etc.)."""
        ...
