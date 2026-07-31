"""Regression for #10920: within_budget must never drop a gauntlet change in
favour of a lower-risk change that merged earlier.

``within_budget`` was an order-preserving greedy prefix fill over the SELECTED
list, and selection order is merge order, not blast radius. So a
``gauntlet``-classified change (weight 4.0, deliberately selected at certainty)
that merged late could be silently truncated by the budget cap while a
``routine`` change that merged earlier was audited — the same escape #10896
closes, reached through the budget stage. The fix fills highest-blast-radius
first, so the budget only ever drops the lowest-risk stratum.
"""

from __future__ import annotations

from audit.budget import estimate_audit_tokens, within_budget
from audit.models import MergedChange

# Blast-radius is classified from changed_paths: ``src/audit/`` → gauntlet,
# an unmarked path → routine (see audit.stratify).
_GAUNTLET_PATHS = ("src/audit/budget.py",)
_ROUTINE_PATHS = ("src/widget.py",)


def _mc(sha: str, paths: tuple[str, ...]) -> MergedChange:
    return MergedChange(
        pr_number=1,
        merge_sha=sha,
        subject="feat: change",
        changed_paths=paths,
        merged_at="2026-07-23T00:00:00+00:00",
        body="",
    )


def test_gauntlet_change_retained_when_routine_merged_earlier() -> None:
    routine = _mc("aaaaaaaaaaaa", _ROUTINE_PATHS)  # merged earlier (first)
    gauntlet = _mc("bbbbbbbbbbbb", _GAUNTLET_PATHS)  # merged later (last)
    # Budget fits exactly one audit (both cost the same — single path).
    budget = estimate_audit_tokens(routine) + 10

    fitted = within_budget([routine, gauntlet], token_budget=budget)
    shas = {c.merge_sha for c in fitted}

    # The gauntlet change is audited; the routine change is the one dropped.
    assert gauntlet.merge_sha in shas
    assert routine.merge_sha not in shas


def test_gauntlet_first_ordering_is_stable_within_a_class() -> None:
    g1 = _mc("g1g1g1g1g1g1", _GAUNTLET_PATHS)
    g2 = _mc("g2g2g2g2g2g2", ("src/audit/models.py",))
    routine = _mc("rrrrrrrrrrrr", _ROUTINE_PATHS)
    # Budget fits two audits.
    budget = estimate_audit_tokens(routine) * 2 + 10

    fitted = within_budget([g1, g2, routine], token_budget=budget)

    # Both gauntlets fit first (stable merge order preserved); routine dropped.
    assert [c.merge_sha for c in fitted] == [g1.merge_sha, g2.merge_sha]
