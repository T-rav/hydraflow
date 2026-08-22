"""State accessor for ErosionMetricsLoop (#10107, epic #10104).

One field: ``erosion_last_processed_sha`` — the base-branch HEAD SHA
ErosionMetricsLoop last finished analyzing. Mirrors
``StagingBisectStateMixin.last_green_rc_sha``'s plain-string-field shape
(``state/_staging_bisect.py``) and ``LogIngestStateMixin``'s
prime-on-first-tick convention (``log_ingest_cursor``): on the very first
tick the cursor is empty, so the loop sets it to the CURRENT HEAD sha and
does no analysis — a fresh install must not back-analyze the repo's entire
history. Every subsequent tick advances the cursor to the sha it just
finished analyzing (whether or not anything was flagged), so a commit
range is analyzed exactly once (dedup by SHA) regardless of how the
per-tick issue-filing cap plays out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ErosionMetricsStateMixin:
    """Last-processed-SHA cursor for ErosionMetricsLoop's change-range scan."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_erosion_last_processed_sha(self) -> str:
        return self._data.erosion_last_processed_sha

    def set_erosion_last_processed_sha(self, sha: str) -> None:
        self._data.erosion_last_processed_sha = sha
        self.save()
