"""Append-only escape-ledger JSONL store (#10367).

``<data_root>/diagnostics/escape_ledger.jsonl`` — one ``EscapeRecord`` per
line, following ``factory_metrics.jsonl``'s append-only-JSONL convention.
The store is deliberately dumb: it appends, reads all, and exposes the set of
already-recorded ids so the caretaker loop dedups a re-detected escape to
exactly one row (idempotent across ticks and restarts). It never mutates or
rewrites existing lines — the ledger is an audit trail, not a mutable table.

A human resolution (confirmed attribution / an encoding) is recorded the same
way: ``append_resolution`` appends a NEW row sharing the original's id rather
than rewriting it. ``read_latest`` gives derived reads (metrics, report, HITL
surfacing) a single current view per id by collapsing to the latest-appended
row (#10498).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from escape.metrics import latest_by_id
from escape.models import EncodedAs, EscapeRecord
from jsonl_ledger import IdentifiedJsonlLedger

logger = logging.getLogger("hydraflow.escape_ledger")


class EscapeLedger(IdentifiedJsonlLedger[EscapeRecord]):
    """Append-only reader/writer over one escape-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, EscapeRecord, logger=logger)

    def read_latest(self) -> list[EscapeRecord]:
        """One row per id — the latest-appended row wins (supersession read)."""
        return latest_by_id(self.read_all())

    def append_resolution(
        self,
        escape_id: str,
        *,
        encoded_as: EncodedAs,
        attribution_confidence: str | None = None,
        notes: str | None = None,
    ) -> EscapeRecord | None:
        """Append a resolution row for *escape_id*, or ``None`` if unknown.

        Builds the new row from the latest existing row for *escape_id*,
        carrying forward every detection/attribution field and overriding
        only the human-decided terminal fields — the original line on disk
        is never touched, only a new one is appended.
        """
        original = next((r for r in self.read_latest() if r.id == escape_id), None)
        if original is None:
            return None
        overrides: dict[str, object] = {"encoded_as": encoded_as}
        if attribution_confidence is not None:
            overrides["attribution_confidence"] = attribution_confidence
        if notes is not None:
            overrides["notes"] = notes
        # `replace()`, not a hand-enumerated kwarg list: a future EscapeRecord
        # field must be carried forward automatically, not silently dropped.
        resolution = replace(original, **overrides)
        self.append(resolution)
        return resolution
