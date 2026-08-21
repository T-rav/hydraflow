"""Regression pins for the #11481 narrowed-closing-verb class.

Class: four sites that need to recognise a GitHub issue-closing reference in
commit/PR text each hand-rolled the identical narrowed regex
(``(?:fixes|closes|resolves)\\s+#(\\d+)``, third-person-singular only, no word
boundaries) instead of importing the canonical ``false_close.CLOSE_KEYWORD_RE``
— which also covers the bare (``Fix``/``Close``/``Resolve``) and past-tense
(``Fixed``/``Closed``/``Resolved``) forms GitHub itself recognizes, anchored
with ``\\b`` word boundaries so e.g. ``prefixes #99`` cannot match. The four
sites:

- ``branch_gc_scan.extract_issue_number`` — StaleIssueLoop's branch-GC
  reconciler silently skipped the truth-comment pass for exactly the
  false-fix-claim branches it was built to catch (#11481, this fix).
- ``pr_manager.PRManager.find_label_drift``'s body scan.
- ``pr_manager.PRManager.find_open_resolving_pr``'s body scan.
- ``pr_manager.PRManager.merge_pr``'s title-anchored cost-attribution match.

Behavioral (bare/past-tense) coverage for the three ``pr_manager`` sites
lives alongside their existing test suites (``tests/test_pr_manager_drift.py``,
``tests/test_pr_manager_find_open_resolving_pr.py``,
``tests/test_pr_manager_issue_cost_alert.py``), reusing their fake-gh
harnesses. This file pins the two facts that make it a single class fix
rather than four independent ones:

1. ``branch_gc_scan`` and ``pr_manager`` both import the SAME regex object
   from ``false_close`` — an identity check so a future edit can't silently
   re-diverge one copy by re-widening it in place instead of reusing the
   import (ADR-0037).
2. The extractor recognises every bare/past-tense closing verb form.
"""

from __future__ import annotations

import branch_gc_scan
import pr_manager
import pytest
from branch_gc_scan import extract_issue_number
from false_close import CLOSE_KEYWORD_RE


def test_branch_gc_scan_reuses_the_canonical_regex_object() -> None:
    assert branch_gc_scan.CLOSE_KEYWORD_RE is CLOSE_KEYWORD_RE


def test_pr_manager_reuses_the_canonical_regex_object() -> None:
    """Covers all three ``pr_manager`` sites (find_label_drift,
    find_open_resolving_pr, merge_pr) at once — each references this same
    module-level name rather than compiling its own copy."""
    assert pr_manager.CLOSE_KEYWORD_RE is CLOSE_KEYWORD_RE


@pytest.mark.parametrize(
    "keyword",
    ["Fix", "Fixed", "Fixes", "Close", "Closed", "Closes", "Resolve", "Resolved", "Resolves"],
)
def test_branch_gc_scan_recognises_every_closing_verb_form(keyword: str) -> None:
    assert extract_issue_number("fix/x", [f"{keyword} #1234"]) == 1234


def test_branch_gc_scan_word_boundary_rejects_substring_match() -> None:
    """``prefixes #99`` must not match — no closing verb precedes it (the
    narrowed pattern this replaces had no word boundary at all, so it also
    would have rejected this; the canonical regex must not regress that)."""
    assert extract_issue_number("fix/x", ["this prefixes #99 somehow"]) == 0
