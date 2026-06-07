"""State accessors for LiveCorpusReplayLoop (#8786 Phase 3).

Per-signature attempt counters for the 3-attempt escalation chain. A drift
signature persists across loop ticks until either:

- The fake catches up (clean tick clears all counters).
- The counter hits the threshold and an escalation issue is filed via
  the ``hitl-escalation`` label — the auto-agent preflight loop picks
  that up and runs its own 3-attempt cycle before human-required fires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class LiveCorpusReplayStateMixin:
    """Per-drift-signature attempt counters."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_live_corpus_drift_attempts(self, signature: str) -> int:
        return int(self._data.live_corpus_drift_attempts.get(signature, 0))

    def inc_live_corpus_drift_attempts(self, signature: str) -> int:
        current = int(self._data.live_corpus_drift_attempts.get(signature, 0)) + 1
        attempts = dict(self._data.live_corpus_drift_attempts)
        attempts[signature] = current
        self._data.live_corpus_drift_attempts = attempts
        self.save()
        return current

    def clear_live_corpus_drift_attempts(self) -> None:
        """Clear ALL counters — called on a clean tick (no drift detected)."""
        if self._data.live_corpus_drift_attempts:
            self._data.live_corpus_drift_attempts = {}
            self.save()

    # --- Fleet-wide shadow-drift rollup tracking (#9351 follow-up) ----------
    # One open ``shadow-drift`` issue is kept per fleet. ``signature_hash`` is
    # the hash of the current diverged-sample set so the loop can skip a
    # redundant body update when the set is unchanged, and close the issue on a
    # clean tick instead of leaving a pile of stale per-tick snapshots.

    def get_live_corpus_drift_rollup(self) -> dict | None:
        """Return ``{'issue_number': int, 'signature_hash': str}`` or ``None``."""
        entry = self._data.live_corpus_drift_rollup
        if not entry:
            return None
        return {
            "issue_number": int(entry.get("issue_number", 0)),
            "signature_hash": str(entry.get("signature_hash", "")),
        }

    def set_live_corpus_drift_rollup(
        self, *, issue_number: int, signature_hash: str
    ) -> None:
        self._data.live_corpus_drift_rollup = {
            "issue_number": int(issue_number),
            "signature_hash": signature_hash,
        }
        self.save()

    def clear_live_corpus_drift_rollup(self) -> None:
        if self._data.live_corpus_drift_rollup is not None:
            self._data.live_corpus_drift_rollup = None
            self.save()

    def get_live_corpus_escalation_issue(self) -> int | None:
        return self._data.live_corpus_escalation_issue or None

    def set_live_corpus_escalation_issue(self, issue_number: int) -> None:
        self._data.live_corpus_escalation_issue = int(issue_number)
        self.save()

    def clear_live_corpus_escalation_issue(self) -> None:
        if self._data.live_corpus_escalation_issue is not None:
            self._data.live_corpus_escalation_issue = None
            self.save()
