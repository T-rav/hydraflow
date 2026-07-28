"""Regression for issue #10753.

The lesson-coverage auditor (``wiki_lesson_coverage``, #10758, shipped in
#10772) flagged three ``left_on_primary`` predecessors whose durable,
live-code lesson had no representation in the terminal successor they were
merged into — orphaned by an N-to-1 synthesis fold (#10566/#10572):

  * ``gotchas/0841`` (``_SHA_MARKER``) — the ``str.splitlines()`` C0-separator
    git-log parsing lesson, folded onto the unrelated hitl-escalation primary
    ``0851`` (chain terminal ``1039``). No active successor carries it, so it
    was re-activated (``status: active``, ``superseded_by`` dropped).
  * ``gotchas/0844`` (``_added_paths_for_range``, ``_fix_subject``,
    ``_SHA_MARKER``) — the ``escape/detect`` merge-race-hazard lesson, same
    fold; re-activated.
  * ``testing/1073`` (``file_memory_suggestion``) — its ``superseded_by`` was
    mis-set to the cartesian round primary ``1085`` (chain terminal ``1377``,
    an unrelated presence/absence-assertion lesson). The lesson actually
    survives into the *active* entry ``1432`` via the title-matching successor
    ``1140``, so the pointer was corrected ``1085`` -> ``1140`` and the
    auditor now resolves it as ``represented``.

This guard runs the auditor over the real ``repo_wiki/`` tree. It fails on the
pre-fix corpus (three orphaned) and guards against a future synthesis round
re-folding these lessons out of the active corpus (#10566).
"""

from __future__ import annotations

from pathlib import Path

from wiki_lesson_coverage import assess_repo_coverage

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACKED_ROOT = _REPO_ROOT / "repo_wiki"
_REPO = "T-rav/hydraflow"

# The three predecessors #10753 restored, as (topic, predecessor_id).
_RESTORED = {("gotchas", "0841"), ("gotchas", "0844"), ("testing", "1073")}


def _report():
    return assess_repo_coverage(_TRACKED_ROOT, _REPO, _REPO_ROOT)


def test_restored_predecessors_are_not_orphaned() -> None:
    report = _report()
    orphaned = {(v.topic, v.predecessor_id) for v in report.orphaned()}
    regressed = _RESTORED & orphaned
    assert not regressed, f"restored lessons regressed to orphaned: {sorted(regressed)}"


def test_testing_1073_lesson_is_represented_in_active_terminal() -> None:
    report = _report()
    verdict = next(
        v
        for topic in report.topics
        if topic.topic == "testing"
        for v in topic.verdicts
        if v.predecessor_id == "1073"
    )
    assert verdict.tier == "represented"
    assert "file_memory_suggestion" in verdict.surviving_anchors
    assert verdict.terminal_id == "1432"


def test_live_corpus_has_no_actionable_orphans() -> None:
    report = _report()
    orphaned = [f"{v.topic}/{v.predecessor_id}" for v in report.orphaned()]
    assert orphaned == [], f"actionable orphaned lessons present: {orphaned}"
