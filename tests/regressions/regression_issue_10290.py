"""Regression guard for #10290 — infra-park must not inherit the 24h backoff.

Triage parks an issue for TWO very different reasons but into ONE state:
* clarification park — the LLM judged the issue needs author input (24h backoff
  via TriageRetryLoop is appropriate: it's waiting on a human);
* infra park — ``self._triage.evaluate()`` raised (rate-limit truncation,
  subprocess exit 1, unparseable verdict). The issue is fine; the infra failed.

Observed live 2026-07-22: a transient infra outage mass-parked ~22 issues; once
infra recovered they were frozen for up to 24h behind the clarification backoff,
and only manual un-parking unstuck them. The fix distinguishes the two via
``StateData.triage_infra_parked`` so TriageRetryLoop re-flows infra-parks on the
short ``triage_infra_retry_interval`` floor.

This guard pins the STATE distinction: the mark/is/clear round-trip, and that
clearing the retry counter (close-reconcile) also drops the infra marker so a
closed-then-reparked issue is classified fresh.
"""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(tmp_path / "state.json")


def test_infra_park_marker_round_trip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.is_triage_infra_parked(10290) is False  # default: not infra-parked

    st.mark_triage_infra_parked(10290)
    assert st.is_triage_infra_parked(10290) is True

    # Idempotent — marking twice keeps a single entry.
    st.mark_triage_infra_parked(10290)
    assert st.to_dict()["triage_infra_parked"].count("10290") == 1

    st.clear_triage_infra_parked(10290)
    assert st.is_triage_infra_parked(10290) is False


def test_marker_persists_across_reload(tmp_path: Path) -> None:
    _tracker(tmp_path).mark_triage_infra_parked(777)
    # A fresh tracker over the same file must still see the marker (infra-park
    # survives a factory restart, so recovery isn't reset by a reboot).
    assert _tracker(tmp_path).is_triage_infra_parked(777) is True


def test_clearing_retry_attempts_also_clears_infra_marker(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.mark_triage_infra_parked(555)
    st.inc_triage_retry_attempts(555)

    # Close-reconcile path clears the retry counter — it must also drop the
    # transient infra marker so a later re-park is classified fresh.
    st.clear_triage_retry_attempts(555)

    assert st.is_triage_infra_parked(555) is False
    assert st.get_triage_retry_attempts(555) == 0
