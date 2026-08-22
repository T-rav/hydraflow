"""State accessors for SampledAuditLoop (#10370).

Three fields — the cursor + the governed-rate state the Shewhart governor
persists between ticks:

* ``sampled_audit_last_processed_sha`` — the base-branch HEAD SHA the sampler
  last finished processing. Mirrors ``escape_ledger_last_processed_sha`` exactly
  (``state/_escape_ledger.py``): empty on the first tick, so the loop primes it
  to the CURRENT HEAD and samples nothing (a fresh install must not back-sample
  the whole history); every subsequent tick advances it to the sha just
  processed (a range is sampled at most once).
* ``sampled_audit_governed_rate`` — the current governed sample rate (0.0 = not
  yet set → the loop uses the 5% base). The governor widens/narrows it by
  Shewhart's rule between the 2% floor and 20% ceiling.
* ``sampled_audit_disagreement_history`` — the bounded per-tick disagreement
  observation series the governor pools to build its control limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import StateData


class SampledAuditStateMixin:
    """Cursor + governed-rate state for SampledAuditLoop."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_sampled_audit_last_processed_sha(self) -> str:
        return self._data.sampled_audit_last_processed_sha

    def set_sampled_audit_last_processed_sha(self, sha: str) -> None:
        self._data.sampled_audit_last_processed_sha = sha
        self.save()

    def get_sampled_audit_governed_rate(self) -> float:
        return self._data.sampled_audit_governed_rate

    def set_sampled_audit_governed_rate(self, rate: float) -> None:
        self._data.sampled_audit_governed_rate = rate
        self.save()

    def get_sampled_audit_disagreement_history(self) -> list[dict[str, Any]]:
        return list(self._data.sampled_audit_disagreement_history)

    def set_sampled_audit_disagreement_history(
        self, history: list[dict[str, Any]]
    ) -> None:
        self._data.sampled_audit_disagreement_history = list(history)
        self.save()
