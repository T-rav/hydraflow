"""#11822: the plan-validation count must survive the HITL hand-off.

`#11544` logged "failed validation — retrying" eleven times, `#11547` seven,
`#11803` six, `#11795` five. Those are not retries. `planner.py` retries
**once**, with the errors in its prompt, and then
`plan_phase_disposition` calls `swap_pipeline_labels(issue, hitl_label)` — so
each entry is a separate HITL cycle that began knowing nothing about the last.

The reason it knew nothing is one line in the hand-off:

    self._state.clear_adversarial_state(issue.id)

Its own comment explains why (unbounded growth of surfacer concerns across
cycles) and it is right to clear that. But nothing took its place, so the
rejection itself was lost too, and cycle N+1 resampled the distribution that
produced the plan cycle N refused — at a full model spawn each.

The counter therefore cannot live in adversarial state. It lives on the
convergence ledger, which the hand-off does not touch. That is the whole
property, and it is what these tests pin.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from plan_validation import rejection_class
from state import StateTracker


def _tracker(path: Path | None = None) -> StateTracker:
    return StateTracker(path or (Path(tempfile.mkdtemp()) / "state.json"))


def test_the_count_survives_the_hitl_handoff() -> None:
    """The exact call the plan phase makes before escalating."""
    state = _tracker()
    for _ in range(3):
        state.bump_plan_validation_rejection(11544, "Simplicity gate")

    state.clear_adversarial_state(11544)

    assert state.get_plan_validation_rejections(11544, "Simplicity gate") == 3, (
        "the rejection count was wiped by the HITL hand-off, so the next "
        "cycle starts blind — which is #11822"
    )


def test_the_count_survives_a_reload_from_disk() -> None:
    """A cycle is a new process, not just a new tick."""
    path = Path(tempfile.mkdtemp()) / "state.json"
    state = _tracker(path)
    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11544, "Simplicity gate")

    reloaded = StateTracker(path)

    assert reloaded.get_plan_validation_rejections(11544, "Simplicity gate") == 2


def test_the_count_is_per_issue() -> None:
    """The decoy: a global counter would pass both assertions above.

    #11544 burned 11 cycles while #11795 burned 5 in the same window. A
    counter that did not separate them would route the wrong issue.
    """
    state = _tracker()
    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11795, "Simplicity gate")

    assert state.get_plan_validation_rejections(11544, "Simplicity gate") == 2
    assert state.get_plan_validation_rejections(11795, "Simplicity gate") == 1


def test_a_cleared_issue_starts_over() -> None:
    """After a decomposition or a plan that lands, the slate resets."""
    state = _tracker()
    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11544, "Simplicity gate")

    state.clear_plan_validation_rejections(11544)

    assert state.get_plan_validation_rejections(11544, "Simplicity gate") == 0


def test_an_untouched_issue_reads_zero() -> None:
    """No ledger row must not raise, and must not read as one rejection."""
    assert _tracker().get_plan_validation_rejections(99999, "Simplicity gate") == 0


# ---------------------------------------------------------------------------
# Per-class counting (operator ruling: N=3, same class)
# ---------------------------------------------------------------------------


def test_different_gates_do_not_add_up() -> None:
    """Three gates once each is not three refusals of one gate.

    #11544 lost nine of its eleven attempts to the duplicate
    enforcement-test gate — one gate refusing the same shape repeatedly, which
    is an issue the planner cannot shrink. An issue that trips three DIFFERENT
    gates once each has three fixable faults, and decomposing it would split
    work that only needed correcting.
    """
    state = _tracker()

    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11544, "Testing gate")
    state.bump_plan_validation_rejection(11544, "Kill-switch gate")

    for cls in ("Simplicity gate", "Testing gate", "Kill-switch gate"):
        assert state.get_plan_validation_rejections(11544, cls) == 1, cls


def test_the_same_gate_accumulates() -> None:
    """The shape that routes: one gate, three refusals."""
    state = _tracker()
    for _ in range(3):
        n = state.bump_plan_validation_rejection(11544, "Simplicity gate")

    assert n == 3
    assert state.get_plan_validation_rejections(11544, "Testing gate") == 0


def test_the_class_is_derived_from_the_error_not_a_hardcoded_list() -> None:
    """A sixth gate must count without anyone registering it.

    The five gates in plan_validation.py today all emit "<Name> gate: <detail>".
    Matching against a literal list of those five would silently stop counting
    the moment a sixth is added — the class of miss where a guard keeps passing
    while its subject grows past it.
    """
    assert rejection_class("Simplicity gate: plan creates 6 new files") == (
        "Simplicity gate"
    )
    assert rejection_class("Simplicity gate: plan creates 11 new files") == (
        "Simplicity gate"
    ), "the same gate at different thresholds must be one class, or it never counts"
    assert rejection_class("Some Future gate: whatever it says") == "Some Future gate"


def test_an_unclassifiable_error_gets_its_own_bucket() -> None:
    """Malformed errors must not pool into a false threshold breach."""
    assert rejection_class("no colon here") == "no colon here"
    assert rejection_class("also no colon") != rejection_class("no colon here")


def test_a_reset_clears_every_class() -> None:
    """After a decomposition, no gate keeps a stale count."""
    state = _tracker()
    state.bump_plan_validation_rejection(11544, "Simplicity gate")
    state.bump_plan_validation_rejection(11544, "Testing gate")

    state.clear_plan_validation_rejections(11544)

    assert state.get_plan_validation_rejections(11544, "Simplicity gate") == 0
    assert state.get_plan_validation_rejections(11544, "Testing gate") == 0
