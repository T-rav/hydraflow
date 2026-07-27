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
surfacing) a single current view per underlying escaping commit by delegating to
the two-stage ``latest_by_escape`` collapse — first by id (a resolution
supersedes its original, #10498), then by ``detection_ref`` so one commit
re-detected under a second source is not double-counted (#10654).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from escape.metrics import escape_by_id, latest_by_escape, latest_by_id
from escape.models import EncodedAs, EscapeRecord
from jsonl_ledger import IdentifiedJsonlLedger

logger = logging.getLogger("hydraflow.escape_ledger")

#: Canonical basename for the append-only escape ledger under
#: ``<data_root>/diagnostics/``. The SINGLE source of truth (#10578) — every
#: caller (``service_registry``, ``EscapeLedgerLoop``, ``SampledAuditLoop``,
#: ``vitals.observe``) resolves the location through this rather than re-hardcoding
#: the literal, the cross-module JSONL-store duplication the concept-scatter
#: sensor (#10104) flags.
ESCAPE_LEDGER_FILENAME = "escape_ledger.jsonl"


class EscapeLedger(IdentifiedJsonlLedger[EscapeRecord]):
    """Append-only reader/writer over one escape-ledger JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, EscapeRecord, logger=logger)

    def read_latest(self) -> list[EscapeRecord]:
        """One row per underlying escaping commit — the supersession read.

        Delegates to the two-stage ``latest_by_escape`` collapse: first by id
        (a resolution supersedes its original, #10498), then by ``detection_ref``
        so one commit re-detected under a second source is not double-counted
        (#10654). This is the single point every consumer reads through.
        """
        return latest_by_escape(self.read_all())

    def read_latest_index(self) -> dict[str, EscapeRecord]:
        """Map every recorded id to the row currently representing its commit.

        The reconcile companion to ``read_latest``. ``read_latest`` collapses by
        ``detection_ref`` and so drops the ids of superseded siblings, but a
        surfacing link is keyed by the exact id it was filed under — an id the
        collapse (#10654) may fold away in favour of a stronger-source sibling.
        This maps EVERY id (id-collapsed) to its ``detection_ref`` winner so a
        folded-away surfaced id still resolves to the current row, and the
        reconcile pass answers it instead of stranding the HITL issue (#10731).
        """
        return escape_by_id(self.read_all())

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

        The lookup runs against the id-collapsed view (``latest_by_id``), not
        the escape-collapsed ``read_latest``: resolution is keyed by the exact
        id, which the ``detection_ref`` collapse (#10654) may fold away in favour
        of a stronger-source sibling — resolving that folded id must still find
        its own latest row rather than silently returning ``None``.
        """
        original = next(
            (r for r in latest_by_id(self.read_all()) if r.id == escape_id), None
        )
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
