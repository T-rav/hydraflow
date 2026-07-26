"""Regression test for issue #10664.

The staging RC dry-run sensor (#10352) flagged the ``s88_pipeline_flow_counts``
sandbox scenario as broken against staging HEAD: it would fail the
``rc/* -> main`` promotion gate. Root cause was drift, not a product bug.

PR #10609 ("drop PR count from the Pipeline Flow strip", commit ``02855e41``)
changed what the ``flow-count-<stage>`` and ``flow-total`` badges render:

  - per-stage badge: ``N · N PR``  ->  ``N``  (bare issue count)
  - pipeline total:  ``N issues · N PRs``  ->  ``N issues``

The Vitest unit tier (``StreamView.test.jsx``) and ``pipelineCounts.js`` were
updated in that PR, but the s88 sandbox e2e scenario's badge-text regexes were
not, so its assertions still demanded the dropped ``· N PR`` / ``· N PRs``
suffix and failed on every real render.

These are pure source/derivation checks: they read the scenario's compiled
regexes and the canonical badge-text literals that the frontend's own Vitest
tests pin, so neither the JS toolchain nor the Docker sandbox is required to run
them (mirrors ``tests/regressions/test_issue_10601.py``). The two sources are
parsed independently so a shared bug can't make them agree spuriously.
"""

from __future__ import annotations

import re
from pathlib import Path

import tests.sandbox_scenarios.scenarios.s88_pipeline_flow_counts as s88

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAMVIEW_TEST_JSX = (
    _REPO_ROOT
    / "src"
    / "ui"
    / "src"
    / "components"
    / "__tests__"
    / "StreamView.test.jsx"
)

# Pre-#10609 badge text — the format the scenario used to (wrongly) still
# require. Kept explicit so the guard fails loudly if the dropped ``PR`` suffix
# is ever reintroduced into the scenario's patterns.
_STALE_STAGE_TEXT = "3 · 0 PR"
_STALE_TOTAL_TEXT = "3 issues · 0 PRs"


def _canonical_flow_count_literals() -> list[str]:
    """Extract the exact ``flow-count-<stage>`` badge texts the UI unit tier pins.

    Reads ``StreamView.test.jsx`` (the frontend's own contract for the badge)
    rather than the scenario, so the scenario's regex is validated against an
    independent source of truth for the rendered format.
    """
    src = _STREAMVIEW_TEST_JSX.read_text(encoding="utf-8")
    literals = re.findall(
        r"getByTestId\('flow-count-[^']+'\)\.textContent\)\.toBe\('([^']+)'\)",
        src,
    )
    assert literals, (
        "no flow-count-<stage> textContent assertions found in "
        f"{_STREAMVIEW_TEST_JSX}; the UI badge contract moved — update this guard"
    )
    return literals


def _canonical_flow_total_literal() -> str:
    """Extract the exact ``flow-total`` badge text the UI unit tier pins."""
    src = _STREAMVIEW_TEST_JSX.read_text(encoding="utf-8")
    literals = re.findall(
        r"getByTestId\('flow-total'\)\.textContent\)\.toBe\('([^']+)'\)",
        src,
    )
    assert literals, (
        "no flow-total textContent assertion found in "
        f"{_STREAMVIEW_TEST_JSX}; the UI badge contract moved — update this guard"
    )
    return literals[0]


def test_s88_stage_pattern_matches_canonical_bare_issue_count_10664() -> None:
    """Every canonical ``flow-count`` badge text must match the scenario regex.

    Post-#10609 the per-stage badge renders a bare issue count (``N``). The
    scenario's ``_STAGE_COUNT_PATTERN`` must accept exactly that, or the sandbox
    e2e fails on a real render — the #10664 break.
    """
    for text in _canonical_flow_count_literals():
        assert s88._STAGE_COUNT_PATTERN.match(text), (
            f"s88 _STAGE_COUNT_PATTERN {s88._STAGE_COUNT_PATTERN.pattern!r} does "
            f"not match the canonical flow-count badge text {text!r} "
            "(src/ui/src/components/__tests__/StreamView.test.jsx)"
        )


def test_s88_total_pattern_matches_canonical_issues_only_10664() -> None:
    """The canonical ``flow-total`` badge text must match the scenario regex.

    Post-#10609 the total renders ``N issues`` (no ``· N PRs`` suffix).
    """
    text = _canonical_flow_total_literal()
    assert s88._TOTAL_COUNT_PATTERN.match(text), (
        f"s88 _TOTAL_COUNT_PATTERN {s88._TOTAL_COUNT_PATTERN.pattern!r} does not "
        f"match the canonical flow-total badge text {text!r} "
        "(src/ui/src/components/__tests__/StreamView.test.jsx)"
    )


def test_s88_patterns_reject_pre_10609_pr_count_format_10664() -> None:
    """The scenario must not require the dropped ``· N PR`` / ``· N PRs`` suffix.

    Guards against reintroducing the stale format that made s88 break against
    staging HEAD in #10664.
    """
    assert s88._STAGE_COUNT_PATTERN.match(_STALE_STAGE_TEXT) is None, (
        "s88 _STAGE_COUNT_PATTERN still accepts the pre-#10609 'N · N PR' format; "
        "the PR count was dropped from the Pipeline Flow strip (#10609)."
    )
    assert s88._TOTAL_COUNT_PATTERN.match(_STALE_TOTAL_TEXT) is None, (
        "s88 _TOTAL_COUNT_PATTERN still accepts the pre-#10609 'N issues · N PRs' "
        "format; the PR count was dropped from the Pipeline Flow strip (#10609)."
    )
