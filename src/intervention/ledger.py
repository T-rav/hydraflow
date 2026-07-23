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

import json
import logging
from pathlib import Path

from intervention.models import InterventionRecord

logger = logging.getLogger("hydraflow.intervention_tally")


class InterventionLedger:
    """Append-only reader/writer over one intervention-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read_all(self) -> list[InterventionRecord]:
        """Return every recorded row; ``[]`` when the ledger doesn't exist yet.

        Malformed lines are skipped (logged) rather than raising — a single
        corrupt append must not blind the whole instrument.
        """
        if not self._path.exists():
            return []
        records: list[InterventionRecord] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("InterventionLedger: skipping malformed ledger line")
                continue
            if isinstance(raw, dict):
                records.append(InterventionRecord.from_json_dict(raw))
        return records

    def existing_ids(self) -> set[str]:
        """Return the set of already-recorded intervention ids (dedup key)."""
        return {r.id for r in self.read_all()}

    def append(self, record: InterventionRecord) -> None:
        """Append one row as a JSONL line, creating the file/dir if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.to_json_dict(), sort_keys=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
