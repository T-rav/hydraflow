"""Pure per-tick token-budget cap on re-audit spend (#10370).

Sampling is the point; a token budget per tick caps total audit spend and
exhaustive re-review is an explicit non-goal. This module estimates the token
cost of one adversarial re-audit and returns how many of a tick's selected
changes fit the budget — so a synthetic backlog can never blow the per-tick
spend (acceptance: the budget is enforced under a synthetic backlog).

The estimate is deliberately CONSERVATIVE (over-counts), so the cap errs toward
under-spending. The dominant cost of one audit is the embedded merged diff,
which the loop truncates to ``MAX_DIFF_CONTEXT_CHARS`` before it reaches the
prompt — so even a single-path change embeds up to that many chars of diff
REGARDLESS of the changed-path count. The earlier ``2000 + 400*paths`` estimate
ignored the diff body and the completion tokens entirely, under-counting a
large single-path audit by 30-50% and making the "over-estimates" claim false;
this estimate now charges the full worst-case diff window plus an output
allowance so real spend genuinely stays at or under the budget.
"""

from __future__ import annotations

from audit.models import MergedChange

# Chars-per-token proxy for embedded English/code text (~4 chars/token). Coarse
# but standard; used to convert the diff-window char cap into a token count.
_CHARS_PER_TOKEN = 4

# The loop truncates each merged diff to this many chars before it reaches the
# prompt. Canonical here (``sampled_audit_loop`` imports it for the truncation)
# so the budget's diff-token charge and the prompt's actual diff window can
# never drift. A large single-path diff embeds up to this whole window.
MAX_DIFF_CONTEXT_CHARS = 12000

# Worst-case diff-body token charge for one audit — path-INDEPENDENT, because a
# single huge file's diff fills the whole truncation window on its own. This is
# the term the old estimate omitted.
_MAX_DIFF_TOKENS = MAX_DIFF_CONTEXT_CHARS // _CHARS_PER_TOKEN

# Fixed per-audit prompt/framing overhead (tokens): the adversarial charter +
# change-metadata boilerplate.
_BASE_AUDIT_TOKENS = 700

# Per-changed-path increment — the path list the prompt enumerates. Small (a
# path is a short string); the diff window, not the path count, dominates.
_PER_PATH_TOKENS = 50

# Output-token allowance: the auditor's completion (JSON verdict + a findings
# paragraph). An input-only estimate under-counts total spend by the whole
# completion, so it is charged explicitly.
_OUTPUT_TOKENS = 800


def estimate_audit_tokens(change: MergedChange) -> int:
    """Conservative token-cost estimate for re-auditing one merged change.

    Charges the full worst-case diff window (``_MAX_DIFF_TOKENS``, since the
    prompt truncates to ``MAX_DIFF_CONTEXT_CHARS`` and even a single-path change
    can fill it), the framing overhead, a per-path increment for the enumerated
    path list, and an output-token allowance. Over-counts by construction.
    """
    return (
        _BASE_AUDIT_TOKENS
        + _MAX_DIFF_TOKENS
        + _PER_PATH_TOKENS * len(change.changed_paths)
        + _OUTPUT_TOKENS
    )


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
