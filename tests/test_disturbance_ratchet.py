"""The disturbance-dampener block-new gate. Rides `make quality`.

Fails a PR if any dimension's current violation count exceeds its baseline (new),
or falls below it without the baseline being pruned in the same change (resolved).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from disturbance.gate import run_gate
from disturbance.registry import DIMENSIONS

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("dimension", [s.name for s in DIMENSIONS])
def test_no_new_or_unpruned_violations(dimension: str) -> None:
    results = run_gate(REPO_ROOT)
    result = results[dimension]
    assert not result.new, (
        f"[{dimension}] new violations introduced (baseline exceeded): {result.new}. "
        f"Fix them, or if intentional, this is the wrong move — the ratchet only shrinks."
    )
    assert not result.resolved, (
        f"[{dimension}] baseline lists violations no longer present: {result.resolved}. "
        f"Prune them from disturbance/baselines/{dimension}.yaml in this change "
        f"(run the snapshot script) so the baseline stays honest."
    )
