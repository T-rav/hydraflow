"""Stuck credit-pause probe for the Tier-1 liveness kernel (#10734).

A live credit pause (the factory deliberately sleeping because the billing
signal is exhausted) looks identical, from the outside, to a *wedged*
``credits_paused_until`` — a pause that should have cleared but did not. Clearing
too eagerly wakes loops onto a genuinely exhausted account and burns the weekly
limit in a retry storm; never clearing wedges the factory forever.

This module distinguishes the two deterministically:

* :func:`classify_credit_pause` (pure) counts *consecutive* paused ticks. A
  single/short pause is left alone; only a pause that persists past a threshold
  arms a corroboration probe.
* :func:`interpret_refresh_response` (pure) reads the backend's
  ``POST /api/control/credit-refresh`` reply — which already corroborates via
  ``probe_credit_availability()`` and no-ops as ``still_exhausted`` on a genuine
  pause — so a confirmed-exhausted account is left paused and a cleared one
  resets the counter.

Stdlib only — must not import ``src/``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

#: Consecutive paused ticks (5-min watchdog cadence) before a pause is treated as
#: possibly wedged and a corroboration probe is armed. At 300s/tick this is ~30
#: min of continuous pause — comfortably longer than any real short pause.
DEFAULT_STUCK_THRESHOLD_TICKS = 6

#: The status string the factory reports while credit-paused.
CREDITS_PAUSED_STATUS = "credits_paused"


class CreditAction(enum.StrEnum):
    """What the credit probe authorises this tick."""

    #: Not paused → clear the consecutive-paused counter.
    RESET = "reset"
    #: Paused, but not yet past the threshold → a live pause; leave it.
    WAIT = "wait"
    #: Paused past the threshold → corroborate via credit-refresh.
    REQUEST_REFRESH = "request_refresh"


class RefreshOutcome(enum.StrEnum):
    """Interpretation of a ``/api/control/credit-refresh`` response."""

    #: Backend confirms the account is still exhausted → leave the pause in place.
    CONFIRMED_EXHAUSTED = "confirmed_exhausted"
    #: Backend resumed (or was not paused) → the wedge is cleared.
    CLEARED = "cleared"


@dataclass(frozen=True)
class CreditDecision:
    """The credit probe's verdict for one tick, plus the counter to persist."""

    action: CreditAction
    paused_ticks: int


def classify_credit_pause(
    *,
    status: str | None,
    paused_ticks: int,
    threshold: int = DEFAULT_STUCK_THRESHOLD_TICKS,
) -> CreditDecision:
    """Pure: classify a credit pause from its consecutive-tick run length.

    * Any non-paused status resets the counter to 0 (RESET).
    * A pause at or below ``threshold`` consecutive ticks is a live pause (WAIT),
      incrementing the counter.
    * A pause that crosses ``threshold`` arms a corroboration probe
      (REQUEST_REFRESH) and resets the counter to 0, so the kernel re-probes at
      most once per ``threshold`` ticks rather than every tick.
    """
    if status != CREDITS_PAUSED_STATUS:
        return CreditDecision(CreditAction.RESET, 0)
    new_ticks = paused_ticks + 1
    if new_ticks > threshold:
        return CreditDecision(CreditAction.REQUEST_REFRESH, 0)
    return CreditDecision(CreditAction.WAIT, new_ticks)


def interpret_refresh_response(response_status: str | None) -> RefreshOutcome:
    """Pure: map a credit-refresh reply to CONFIRMED_EXHAUSTED / CLEARED.

    ``resuming`` / ``not_paused`` mean the wedge cleared; anything else —
    ``still_exhausted``, an error, or an unreadable reply — is treated as a
    genuine, confirmed pause and left in place (fail-closed: never wake loops
    onto an account we could not confirm has credit).
    """
    if response_status in {"resuming", "not_paused"}:
        return RefreshOutcome.CLEARED
    return RefreshOutcome.CONFIRMED_EXHAUSTED
