"""Generic append-only JSONL ledger base (#10404).

Lifts the byte-identical read/append/dedup logic that had independently
accreted in ``audit.store.AuditSampleLedger``, ``escape.ledger.EscapeLedger``,
and ``intervention.ledger.InterventionLedger`` (concept-scatter erosion
finding, issue #10404) into one shared base. Each domain still owns its own
subclass, record model, and any domain-specific mutation (e.g.
``AuditSampleLedger.update_dispositions``) — this only lifts the shared file
I/O.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Generic, Protocol, Self, TypeVar


class Recordable(Protocol):
    """Structural contract for one JSONL-ledger row."""

    @property
    def id(self) -> str: ...

    def to_json_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> Self: ...


T = TypeVar("T", bound=Recordable)


class JsonlLedger(Generic[T]):
    """Append-only reader/writer over one JSONL ledger file."""

    def __init__(
        self, path: Path, record_cls: type[T], *, logger: logging.Logger
    ) -> None:
        self._path = path
        self._record_cls = record_cls
        self._logger = logger

    @property
    def path(self) -> Path:
        return self._path

    def read_all(self) -> list[T]:
        """Return every recorded row; ``[]`` when the ledger doesn't exist yet.

        Malformed lines are skipped (logged) rather than raising — a single
        corrupt append must not blind the whole instrument.
        """
        if not self._path.exists():
            return []
        records: list[T] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                self._logger.warning(
                    "%s: skipping malformed ledger line", type(self).__name__
                )
                continue
            if isinstance(raw, dict):
                records.append(self._record_cls.from_json_dict(raw))
        return records

    def existing_ids(self) -> set[str]:
        """Return the set of already-recorded row ids (dedup key)."""
        return {r.id for r in self.read_all()}

    def append(self, record: T) -> None:
        """Append one row as a JSONL line, creating the file/dir if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.to_json_dict(), sort_keys=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
