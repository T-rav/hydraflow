"""The ViolationDetector protocol (the Sensor role, ADR-0094)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from disturbance.models import Finding

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping


class ViolationDetector(Protocol):
    name: str

    def detect(self, repo_root: Path) -> list[Finding]:
        """Return all current findings for this dimension. Pure: reads files only."""
        ...

    def reachable_ceilings(self) -> Mapping[str, int]:
        """Signatures whose emitted count has a FINITE maximum, and that maximum.

        The gate's block-new arm fires on ``cur > base``. When a signature's
        largest reachable count is <= its baseline, that arm is
        ARITHMETICALLY DEAD: no input the detector can produce reddens it,
        and the dimension keeps reporting a clean ratchet while blocking
        nothing. ``disturbance.gate.run_gate`` refuses such a configuration
        rather than running a gate that cannot fail.

        Return the ceiling for every signature the detector caps. A
        signature absent from the mapping is unbounded — there is always a
        reachable count above any baseline, so its arm is live by
        construction.

        Required, not optional: a detector that quietly inherited "unbounded"
        would reintroduce exactly the blind spot this method exists to close.
        """
        ...
