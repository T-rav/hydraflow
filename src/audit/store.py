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

logger = logging.getLogger("hydraflow.sampled_audit")


class AuditSampleLedger:
    """Append-only reader/writer over one ``audit_samples.jsonl`` file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read_all(self) -> list[AuditSample]:
        """Return every recorded sample; ``[]`` when the file doesn't exist yet.

        Malformed lines are skipped (logged) rather than raising — a single
        corrupt append must not blind the whole instrument.
        """
        if not self._path.exists():
            return []
        samples: list[AuditSample] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("AuditSampleLedger: skipping malformed line")
                continue
            if isinstance(raw, dict):
                samples.append(AuditSample.from_json_dict(raw))
        return samples

    def existing_ids(self) -> set[str]:
        """Return the set of already-recorded sample ids (dedup key)."""
        return {s.id for s in self.read_all()}

    def append(self, sample: AuditSample) -> None:
        """Append one row as a JSONL line, creating the file/dir if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(sample.to_json_dict(), sort_keys=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")

    def update_dispositions(self, updated: dict[str, AuditSample]) -> None:
        """Rewrite the file, replacing rows in *updated* by id.

        Used only by the adjudication reconcile — every other write is a pure
        append. A no-op when *updated* is empty or the file is absent.
        """
        if not updated or not self._path.exists():
            return
        rows = self.read_all()
        with self._path.open("w", encoding="utf-8") as fh:
            for row in rows:
                out = updated.get(row.id, row)
                fh.write(json.dumps(out.to_json_dict(), sort_keys=False) + "\n")
