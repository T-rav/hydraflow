"""Append-only audit-sample JSONL store (#10370).

``<data_root>/diagnostics/audit_samples.jsonl`` — one ``AuditSample`` per line,
following ``escape_ledger.jsonl``'s append-only-JSONL convention. Appends,
reads all, exposes already-recorded ids for dedup, and supports an in-place
disposition update (the ONE mutation: an adjudicated disagreement's disposition
is reconciled from ``pending`` — the audit trail is otherwise immutable).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from audit.models import AuditSample
from jsonl_ledger import JsonlLedger

logger = logging.getLogger("hydraflow.sampled_audit")


class AuditSampleLedger(JsonlLedger[AuditSample]):
    """Append-only reader/writer over one ``audit_samples.jsonl`` file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, AuditSample, logger=logger)

    def update_dispositions(self, updated: dict[str, AuditSample]) -> None:
        """Rewrite the file, replacing rows in *updated* by id.

        Used only by the adjudication reconcile — every other write is a pure
        append. A no-op when *updated* is empty or the file is absent.
        """
        if not updated or not self.path.exists():
            return
        rows = self.read_all()
        with self.path.open("w", encoding="utf-8") as fh:
            for row in rows:
                out = updated.get(row.id, row)
                fh.write(json.dumps(out.to_json_dict(), sort_keys=False) + "\n")
