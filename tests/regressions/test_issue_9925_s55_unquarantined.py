"""Regression: s55_nested_decompose stays un-quarantined and CI-gated (#9925).

s55 was quarantined under #9925 as "born-racy". The real defect was NOT a
decompose/review race (the issue's original diagnosis) but the #9796
DiscoverRunner/ShapeRunner air-gapped-sandbox wedge — s55's children pass
through discover/shape with no seeded script, so those runners spawned a real
``claude`` and ran to ``agent_timeout``, freezing the phase loop so a child
never reached review→escalate→decompose and the epic stalled at 50%. #9919
fixed that wedge (landing 28 min after the quarantine, so it silently fixed s55
too), proven by 31/31 consecutive green docker runs.

These pins guard the un-quarantine from silently regressing: re-adding the
QUARANTINED marker, dropping s55 from the collective run set, or removing it
from the CI fast subset would each re-open the coverage gap #9925 tracked.
"""

from __future__ import annotations

from pathlib import Path

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _s55_module():
    return next(
        m
        for m in load_all_scenarios(include_quarantined=True)
        if m.NAME == "s55_nested_decompose"
    )


def test_s55_carries_no_quarantine_marker() -> None:
    # A QUARANTINED marker would pull s55 back out of collective runs. The
    # #9796 wedge fix (#9919) resolved the flake — re-quarantining requires a
    # fresh tracking issue and a real, unfixed defect, not a silent regression.
    assert getattr(_s55_module(), "QUARANTINED", None) is None


def test_s55_is_in_the_collective_run_set() -> None:
    # load_all_scenarios() (no include_quarantined) is the collective set used
    # by run-all; s55 must be in it so RC promotion exercises nested decompose.
    collective = {m.NAME for m in load_all_scenarios()}
    assert "s55_nested_decompose" in collective


def test_s55_is_in_the_ci_fast_subset() -> None:
    # The PR→staging fast-subset list in ci.yml is hardcoded (kept in sync with
    # the quarantine markers by hand). Pin that s55 is present so it can't be
    # dropped from PR-time coverage without this test failing.
    ci_yml = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    fast_line = next(
        (ln for ln in ci_yml.splitlines() if "for s in s01_happy_single_issue" in ln),
        "",
    )
    assert "s55_nested_decompose" in fast_line, (
        "s55_nested_decompose missing from ci.yml's PR→staging fast subset loop"
    )
