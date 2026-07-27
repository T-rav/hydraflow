"""Fingerprint -> filed-issue-number link store for the escape ledger (#10577).

``<data_root>/diagnostics/escape_surfaces.jsonl`` — one ``SurfacedIssue`` per
line, tying a HITL/``hydraflow-find`` issue that ``EscapeLedgerLoop`` filed for
a surfacing back to the ledger row that produced it. Before this store the loop
awaited ``PRPort.create_issue`` (which RETURNS the new issue number) and threw
the number away, keeping only the reason-scoped dedup fingerprint
(``surfaced:<reason>:<id>``) — a bare string that mapped nothing back to the
issue, so a later resolution could never close the stranded HITL surface.

``DedupStore`` is a set of strings and cannot hold that mapping, so this is a
separate append-only sidecar built on the shared ``IdentifiedJsonlLedger`` base
(``id`` = the surfacing fingerprint), mirroring ``escape.ledger.EscapeLedger``.
State supersedes last-row-wins per fingerprint — the same convention as
``EscapeLedger.append_resolution`` — so a terminal ``closed`` row is idempotent
across restarts and the reconcile pass files exactly one comment+close per link.
The dedup fingerprint format is unchanged: the issue number lives here as
separate metadata, never encoded into the fingerprint (which would break the
exact-match one-shot budget in ``select_findings_to_surface``, #10503).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jsonl_ledger import IdentifiedJsonlLedger

logger = logging.getLogger("hydraflow.escape_ledger")


@dataclass(frozen=True)
class SurfacedIssue:
    """One append-only link row: a filed HITL issue for one surfacing.

    ``fingerprint`` is the reason-scoped surfacing key (``surfaced:<reason>:<id>``)
    and doubles as the ledger dedup id. ``closed_at`` is empty while the link is
    open; a non-empty value marks the terminal, already-reconciled state.
    """

    fingerprint: str
    escape_id: str
    reason: str
    issue_number: int
    filed_at: str
    closed_at: str = ""

    @property
    def id(self) -> str:
        """Stable dedup key = the surfacing fingerprint (one link per surfacing)."""
        return self.fingerprint

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSONL payload."""
        return {
            "fingerprint": self.fingerprint,
            "escape_id": self.escape_id,
            "reason": self.reason,
            "issue_number": self.issue_number,
            "filed_at": self.filed_at,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> SurfacedIssue:
        """Parse one JSONL row, tolerant of missing optional fields."""
        return cls(
            fingerprint=str(raw.get("fingerprint", "")),
            escape_id=str(raw.get("escape_id", "")),
            reason=str(raw.get("reason", "")),
            issue_number=int(raw.get("issue_number", 0) or 0),
            filed_at=str(raw.get("filed_at", "")),
            closed_at=str(raw.get("closed_at", "")),
        )


def _latest_by_fingerprint(rows: list[SurfacedIssue]) -> list[SurfacedIssue]:
    """Collapse *rows* to one per fingerprint — the latest-appended row wins.

    Mirrors ``escape.metrics.latest_by_id``: order of first appearance is
    preserved, the content kept per fingerprint is whichever row appeared last
    (so an appended ``closed`` row supersedes its ``open`` predecessor).
    """
    latest: dict[str, SurfacedIssue] = {}
    order: list[str] = []
    for row in rows:
        if row.fingerprint not in latest:
            order.append(row.fingerprint)
        latest[row.fingerprint] = row
    return [latest[fp] for fp in order]


class SurfacedIssueLedger(IdentifiedJsonlLedger[SurfacedIssue]):
    """Append-only reader/writer over one escape-surfaces JSONL file."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, SurfacedIssue, logger=logger)

    def append_surfaced(
        self,
        *,
        fingerprint: str,
        escape_id: str,
        reason: str,
        issue_number: int,
        filed_at: str,
    ) -> SurfacedIssue:
        """Append an OPEN link row for a freshly filed HITL issue."""
        row = SurfacedIssue(
            fingerprint=fingerprint,
            escape_id=escape_id,
            reason=reason,
            issue_number=issue_number,
            filed_at=filed_at,
        )
        self.append(row)
        return row

    def append_closed(self, link: SurfacedIssue, *, closed_at: str) -> SurfacedIssue:
        """Append a terminal CLOSED row superseding *link* (last-row-wins)."""
        row = replace(link, closed_at=closed_at)
        self.append(row)
        return row

    def open_links(self) -> list[SurfacedIssue]:
        """Links with no terminal ``closed`` row — the reconcile candidates."""
        return [
            row for row in _latest_by_fingerprint(self.read_all()) if not row.closed_at
        ]
