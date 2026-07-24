"""Append-only escape-ledger JSONL store (#10367).

``<data_root>/diagnostics/escape_ledger.jsonl`` — one ``EscapeRecord`` per
line, following ``factory_metrics.jsonl``'s append-only-JSONL convention.
The store is deliberately dumb: it appends, reads all, and exposes the set of
already-recorded ids so the caretaker loop dedups a re-detected escape to
exactly one row (idempotent across ticks and restarts). It never mutates or
rewrites existing lines — the ledger is an audit trail, not a mutable table.
"""

from __future__ import annotations

import logging
from pathlib import Path

from escape.models import EscapeRecord
from jsonl_ledger import JsonlLedger

logger = logging.getLogger("hydraflow.escape_ledger")


class EscapeLedger(JsonlLedger[EscapeRecord]):
    """Append-only reader/writer over one escape-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, EscapeRecord, logger=logger)
