"""Pure per-tick token-budget cap on re-audit spend (#10370).

Sampling is the point; a token budget per tick caps total audit spend and
exhaustive re-review is an explicit non-goal. This module estimates the token
cost of one adversarial re-audit from the merged diff size and returns how many
of a tick's selected changes fit the budget — so a synthetic backlog can never
blow the per-tick spend (acceptance: the budget is enforced under a synthetic
backlog).
"""

from __future__ import annotations

from audit.models import MergedChange

# Fixed per-audit prompt/framing overhead (tokens) plus a per-changed-path
# increment — a coarse but monotonic proxy for diff size. Deliberately
# conservative (over-estimates), so the cap errs toward under-spending.
_BASE_AUDIT_TOKENS = 2000
_PER_PATH_TOKENS = 400


def estimate_audit_tokens(change: MergedChange) -> int:
    """Coarse token-cost estimate for re-auditing one merged change."""
    return _BASE_AUDIT_TOKENS + _PER_PATH_TOKENS * len(change.changed_paths)


def within_budget(
    selected: list[MergedChange], *, token_budget: int
) -> list[MergedChange]:
    """Return the prefix of *selected* whose cumulative estimate fits *budget*.

    Order-preserving greedy fill: accumulate ``estimate_audit_tokens`` until the
    next audit would exceed *token_budget*, then stop. A non-positive budget
    audits nothing. Because the estimate over-counts, the real spend stays at or
    under the budget.
    """
    if token_budget <= 0:
        return []
    fitted: list[MergedChange] = []
    spent = 0
    for change in selected:
        cost = estimate_audit_tokens(change)
        if spent + cost > token_budget:
            break
        spent += cost
        fitted.append(change)
    return fitted
