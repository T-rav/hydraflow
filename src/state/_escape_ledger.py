"""State accessor for EscapeLedgerLoop (#10367).

One field: ``escape_ledger_last_processed_sha`` — the base-branch HEAD SHA
EscapeLedgerLoop last finished analyzing for escapes. Mirrors
``ErosionMetricsStateMixin.erosion_last_processed_sha`` exactly
(``state/_erosion_metrics.py``): on the very first tick the cursor is empty,
so the loop primes it to the CURRENT HEAD sha and does no analysis — a fresh
install must not back-analyze the repo's entire history (the one-time
explicit backfill command, if provided, is separate). Every subsequent tick
advances the cursor to the sha it just finished analyzing, so a commit range
is analyzed exactly once (dedup by SHA) regardless of how the per-tick
issue-filing cap plays out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class EscapeLedgerStateMixin:
    """Last-processed-SHA cursor for EscapeLedgerLoop's escape-detection scan."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_escape_ledger_last_processed_sha(self) -> str:
        return self._data.escape_ledger_last_processed_sha

    def set_escape_ledger_last_processed_sha(self, sha: str) -> None:
        self._data.escape_ledger_last_processed_sha = sha
        self.save()
