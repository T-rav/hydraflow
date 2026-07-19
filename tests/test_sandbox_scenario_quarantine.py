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
    assert "s55_nested_decompose" in quarantined  # #9925 — drop with the fix


def test_explicit_load_includes_quarantined_scenarios() -> None:
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
    assert hidden == {"s55_nested_decompose"}, (
        f"unexpected quarantine set {hidden} — adding a quarantine requires "
        f"updating this pin (and a tracking issue), removing one means the "
        f"fix landed: update both here"
    )
