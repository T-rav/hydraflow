"""Regression: batch dispatch must detect overlapping scope before building (#10778).

The 2026-07-27 break/fix cycle: #10772 (lesson-survival) and #10773
(wiki-citations) were dispatched in one batch, both touched issue #10754 and the
same ``wiki_rot_*.py`` files, and resolved #10754 contradictorily (one built the
tool → citations valid; the other removed the citations assuming no tool),
forcing a manual rebase + semantic reconcile.

This pins the dispatch-time guard: two concurrently-dispatched units that share a
referenced issue number OR an identical concrete file path are detected, so the
second is held (serialized) rather than built alongside the first — while
genuinely independent units are never held.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from dispatch_overlap import DispatchOverlapTracker
from models import Task


def _task(id: int, body: str) -> Task:
    return Task(id=id, title="", body=body)


def test_batch_siblings_sharing_issue_10754_are_held() -> None:
    tracker = DispatchOverlapTracker()
    tracker.reserve_or_hold(_task(10772, "lesson survival — resolves #10754"))
    decision = tracker.reserve_or_hold(_task(10773, "wiki citations — also #10754"))
    assert decision is not None and decision.reason.kind == "issue"


def test_held_sibling_names_the_first_as_the_blocker() -> None:
    tracker = DispatchOverlapTracker()
    tracker.reserve_or_hold(_task(10772, "lesson survival — resolves #10754"))
    decision = tracker.reserve_or_hold(_task(10773, "wiki citations — also #10754"))
    assert decision is not None and decision.blocking_id == 10772


def test_batch_siblings_sharing_wiki_rot_files_are_held() -> None:
    tracker = DispatchOverlapTracker()
    tracker.reserve_or_hold(_task(10772, "edits the `wiki_rot_reconcile.py` module"))
    decision = tracker.reserve_or_hold(
        _task(10773, "also rewrites `wiki_rot_reconcile.py`")
    )
    assert decision is not None and decision.reason.kind == "file"


def test_independent_units_are_not_held() -> None:
    tracker = DispatchOverlapTracker()
    tracker.reserve_or_hold(
        _task(10772, "fix flake in tests/test_alpha.py, see #10754")
    )
    decision = tracker.reserve_or_hold(
        _task(10773, "add config knob in src/beta.py, see #10999")
    )
    assert decision is None
