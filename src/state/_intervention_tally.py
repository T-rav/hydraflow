"""State accessor for InterventionTallyLoop (#10369).

One field: ``intervention_tally_last_processed_ts`` — the ISO-8601 timestamp
InterventionTallyLoop last processed the event/steering streams up to. Mirrors
``EscapeLedgerStateMixin``'s cursor shape (``state/_escape_ledger.py``), but a
timestamp instead of a SHA because the source is an event stream, not a commit
range: on the very first tick the cursor is empty, so the loop primes it to
NOW and does no back-analysis — a fresh install must not re-classify the whole
event history. Every subsequent tick advances the cursor to the tick's start
time, so each human touch is processed exactly once (touches are sensed
strictly after the cursor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class InterventionTallyStateMixin:
    """Last-processed-timestamp cursor for InterventionTallyLoop's event scan."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_intervention_tally_last_processed_ts(self) -> str:
        return self._data.intervention_tally_last_processed_ts

    def set_intervention_tally_last_processed_ts(self, ts: str) -> None:
        self._data.intervention_tally_last_processed_ts = ts
        self.save()
