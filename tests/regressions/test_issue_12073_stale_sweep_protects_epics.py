"""#12073: the stale sweep auto-closed epic children, undoing epic burn-down.

`StaleIssueLoop._do_work` built `exclude_labels` by hand from the four pipeline
stage labels plus `settings.excluded_labels` (which defaults to empty). So an
issue carrying `hydraflow-epic`, `hydraflow-epic-child` or `human-required` and
no stage label was swept after `staleness_days` (30) and auto-closed.

That is a false close with a recurrence mechanism: reopening the issue as
tracked-but-unscheduled work makes it eligible again on the next quiet window.

`backlog_budget.PROTECTED_LABELS` already existed as the canonical "untouchable
regardless of age or budget" set, and this module already imported from that
file — for `RETIREMENT_COMMENT`, not for protection. The fix is to consume the
shared set rather than maintain a second list, because two lists over one
concept is how they drift apart.

The `human-required` exposure is wider than the issue reported: those issues are
open precisely because they are waiting on a person, so a quiet month is their
normal state rather than evidence of staleness.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from backlog_budget import PROTECTED_LABELS  # noqa: E402

_SWEEP = Path(__file__).parents[2] / "src" / "stale_issue_loop.py"


def test_the_sweep_consumes_the_shared_protected_set() -> None:
    """Not a second hand-built list — the same one the budget valve uses."""
    source = _SWEEP.read_text(encoding="utf-8")

    assert "PROTECTED_LABELS" in source, (
        "the stale sweep does not reference the canonical protected set; a "
        "second list over one concept is how epic labels went missing"
    )
    assert "*PROTECTED_LABELS," in source, (
        "PROTECTED_LABELS is imported but not spread into exclude_labels"
    )


@pytest.mark.parametrize(
    "label",
    [
        "hydraflow-epic",
        "hydraflow-epic-child",
        "human-required",
    ],
)
def test_a_quiet_issue_with_this_label_is_never_swept(label: str) -> None:
    """The three the hand-built list missed, named so a regression is legible.

    Parametrised over the labels this issue is ABOUT rather than over
    PROTECTED_LABELS itself: the point is that these three specific ones were
    sweepable, and a future edit that drops one from the shared set should fail
    here with its name rather than silently shrink a derived list.
    """
    assert label in PROTECTED_LABELS, (
        f"{label!r} left PROTECTED_LABELS — an issue carrying it becomes "
        f"eligible for the stale auto-close sweep again (#12073)"
    )


def test_the_pipeline_stages_are_still_excluded_too() -> None:
    """The original four must survive the change — this widened, not replaced."""
    source = _SWEEP.read_text(encoding="utf-8")

    for dial in ("planner_label", "ready_label", "review_label", "hitl_label"):
        assert f"*self._config.{dial}," in source, (
            f"{dial} was dropped from exclude_labels; the fix must widen the "
            f"exclusion, not swap one incomplete list for another"
        )
