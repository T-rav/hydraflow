"""Ratchet: a fixture can't be silently shrunk out of criterion 6 (#10860).

``score_long_context_placement`` (criterion 6) returns ``N/A`` below
``LONG_CONTEXT_THRESHOLD`` (10,000 chars) — a 10k prompt of pure instructions has
no embedded context to misplace. So shrinking a fixture that currently *scores*
criterion 6 below the threshold flips its result to ``N/A``: the Fail disappears
and the baseline tightens, recording a gate-gaming shrink as a win. That is the
"perverse incentive to fix alongside" #10860 calls out — the gate rewards less
representative test data.

This pins the set of fixtures currently in criterion-6 territory so the set can
only change by an explicit, reviewable edit: shrinking one out (removing it here
acknowledges criterion 6 no longer applies) or growing a new one in (adding it
protects it from a later silent shrink). It does not fix the broader
branch-coverage gap (67-73% of the high-blast-radius builders) — that
fixture-realism scorecard is the larger follow-up; this closes the gaming vector.
"""

from __future__ import annotations

from scripts import audit_prompts as audit
from scripts.audit_prompts import LONG_CONTEXT_THRESHOLD, PROMPT_REGISTRY

#: Fixtures whose rendered length is ``>= LONG_CONTEXT_THRESHOLD`` today, so
#: criterion 6 actually scores them. Keep this EXACTLY equal to the current
#: over-threshold set (the test enforces both directions).
#:
#: The agent + reviewer prompts were intentionally shrunk below the threshold by
#: the #10860 long-prompt prune (PR #10981) — a legitimate token reduction, not a
#: gate-gaming shrink: criterion 6 was *passing* for all of them (their
#: PROMPT_BASELINE failing sets are {1} / {1,3,7} — 6 is absent), so the flip to
#: N/A erases no Fail. Per this test's contract they are removed here to
#: acknowledge criterion 6 no longer applies. The fixtures below all stayed
#: >= threshold after the prune and remain protected.
#: ``agent_build_prompt_with_prior_failure`` joined when the render became
#: host-hermetic: the ``## Available Skills`` section (deterministic
#: ``_AUDIT_PLUGIN_SKILLS`` since the host-independence fix — see
#: tests/regressions/test_audit_render_host_independent.py) now renders on
#: every host, and the #11065 self-check checklist growth put this fixture at
#: 10,231 chars. Previously CI rendered it at 8,808 (no plugin cache on the
#: runner) while developer machines rendered 10,231 — the pin test literally
#: disagreed with itself across hosts.
_LONG_CONTEXT_FIXTURES = frozenset(
    {
        "agent_build_prompt_with_prior_failure",
        "decomposition_ensemble_validation",
        "planner_build_prompt_first_attempt",
        "preflight_auto_agent",
        "review_advisor_postverify",
        "shape_runner_turn",
    }
)


def _fixtures_over_threshold() -> set[str]:
    over: set[str] = set()
    for target in PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        if len(audit.render_target(target)) >= LONG_CONTEXT_THRESHOLD:
            over.add(target.name)
    return over


def test_criterion6_fixture_set_is_pinned() -> None:
    over = _fixtures_over_threshold()
    dropped = sorted(_LONG_CONTEXT_FIXTURES - over)
    grew = sorted(over - _LONG_CONTEXT_FIXTURES)
    assert not dropped, (
        f"fixture(s) {dropped} fell below LONG_CONTEXT_THRESHOLD "
        f"({LONG_CONTEXT_THRESHOLD}), which silently turns their criterion-6 "
        "result into N/A — a gate-gaming shrink (#10860). Restore the rendered "
        "length, or if the shrink is intentional, remove them from "
        "_LONG_CONTEXT_FIXTURES to acknowledge criterion 6 no longer applies."
    )
    assert not grew, (
        f"fixture(s) {grew} now render >= LONG_CONTEXT_THRESHOLD, so criterion 6 "
        "scores them — add them to _LONG_CONTEXT_FIXTURES so a later silent "
        "shrink back under the threshold cannot erase the score unnoticed."
    )
