"""Append-only intervention-ledger JSONL store (#10369).

``<data_root>/diagnostics/intervention_ledger.jsonl`` — one
``InterventionRecord`` per line, following ``escape_ledger.jsonl``'s
append-only-JSONL convention (the deliberately-shared sibling shape). The
store is dumb: it appends, reads all, and exposes the set of already-recorded
ids so the caretaker loop dedups a re-sensed touch to exactly one row
(idempotent across ticks and restarts). It never mutates or rewrites existing
lines — the ledger is an audit trail, not a mutable table.
"""

from __future__ import annotations

import logging
from pathlib import Path

from intervention.models import InterventionRecord
from jsonl_ledger import JsonlLedger

logger = logging.getLogger("hydraflow.intervention_tally")


class InterventionLedger(JsonlLedger[InterventionRecord]):
    """Append-only reader/writer over one intervention-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, InterventionRecord, logger=logger)
