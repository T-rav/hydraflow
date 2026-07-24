"""Append-only escape-ledger JSONL store (#10367).

``<data_root>/diagnostics/escape_ledger.jsonl`` — one ``EscapeRecord`` per
line, following ``factory_metrics.jsonl``'s append-only-JSONL convention.
The store is deliberately dumb: it appends, reads all, and exposes the set of
already-recorded ids so the caretaker loop dedups a re-detected escape to
exactly one row (idempotent across ticks and restarts). It never mutates or
rewrites existing lines — the ledger is an audit trail, not a mutable table.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from escape.models import EscapeRecord

logger = logging.getLogger("hydraflow.escape_ledger")


class EscapeLedger:
    """Append-only reader/writer over one escape-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read_all(self) -> list[EscapeRecord]:
        """Return every recorded row; ``[]`` when the ledger doesn't exist yet.

        Malformed lines are skipped (logged) rather than raising — a single
        corrupt append must not blind the whole instrument.
        """
        if not self._path.exists():
            return []
        records: list[EscapeRecord] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("EscapeLedger: skipping malformed ledger line")
                continue
            if isinstance(raw, dict):
                records.append(EscapeRecord.from_json_dict(raw))
        return records

    def existing_ids(self) -> set[str]:
        """Return the set of already-recorded escape ids (dedup key)."""
        return {r.id for r in self.read_all()}

    def append(self, record: EscapeRecord) -> None:
        """Append one row as a JSONL line, creating the file/dir if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.to_json_dict(), sort_keys=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
