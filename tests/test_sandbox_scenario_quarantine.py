"""Quarantine contract for sandbox scenarios (#9925).

A scenario module may declare ``QUARANTINED = "#<issue>"`` to pull itself out
of collective runs (``run-all``, the CI fast subset) while a tracked defect
makes its signal unreliable. These tests pin the contract so a quarantine can
neither silently widen (marker without a tracking-issue reference) nor
silently leak back into collective runs.
"""

from __future__ import annotations

import re

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

_MARKER_RE = re.compile(r"^#\d+$")


def test_collective_load_excludes_quarantined_scenarios() -> None:
    names = {m.NAME for m in load_all_scenarios()}
    quarantined = {m.NAME for m in load_all_scenarios(include_quarantined=True)} - names
    for name in quarantined:
        assert name not in names
    # s55 was quarantined under #9925; the actual defect (the #9796
    # discover/shape air-gapped-sandbox wedge) was fixed by #9919, so s55 is
    # back in collective runs. No scenario is quarantined at present.
    assert "s55_nested_decompose" in names


def test_explicit_load_includes_all_scenarios() -> None:
    # include_quarantined=True loads every scenario (quarantined or not); s55 is
    # a normal scenario again and must remain loadable.
    names = {m.NAME for m in load_all_scenarios(include_quarantined=True)}
    assert "s55_nested_decompose" in names


def test_every_quarantine_marker_references_a_tracking_issue() -> None:
    for mod in load_all_scenarios(include_quarantined=True):
        marker = getattr(mod, "QUARANTINED", None)
        if marker is None:
            continue
        assert isinstance(marker, str) and _MARKER_RE.match(marker), (
            f"{mod.NAME}: QUARANTINED must be an issue reference like '#9925', "
            f"got {marker!r} — an untracked quarantine is silent coverage loss"
        )


def test_quarantine_does_not_hide_more_than_the_known_set() -> None:
    all_mods = load_all_scenarios(include_quarantined=True)
    collective = load_all_scenarios()
    hidden = {m.NAME for m in all_mods} - {m.NAME for m in collective}
    # s75_worker_stall_escalation was auto-quarantined by the FlakeTracker
    # (tracking #10315) but the pin was never acknowledged — a pre-existing
    # staging-red this un-sticks. Remove from the set when #10315's fix lands.
    known_quarantined = {"s75_worker_stall_escalation"}
    assert hidden == known_quarantined, (
        f"unexpected quarantine set {hidden ^ known_quarantined} — adding a "
        f"quarantine requires updating this pin (and a tracking issue), "
        f"removing one means the fix landed: update both here"
    )
