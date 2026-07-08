"""MockWorld scenario — convergence gate recording at triage and plan boundaries.

Proves that the boundary recording introduced in Tasks 2–4 fires through REAL
phase code, not hand-populated ledger entries.  A single issue is driven through
the full MockWorld pipeline (triage → plan → implement → review) with the gate
ON, and the test asserts the ledger accumulates ``stage_state`` entries for
``"triage"`` and ``"plan"``, both with ``last_verdict == "ADVANCE"``.

**Integration-level** — the real ``triage_phase`` and ``plan_phase`` run inside
MockWorld; nothing in the ledger is set by hand.  This complements
``test_convergence_review_mockworld.py``, which covers the review boundary.

Note: ``run_pipeline`` does NOT run a shape phase, so no ``"shape"`` assertion
is made.  The pipeline order is triage → plan → implement → review.

**Golden-path adaptation (clear-on-merge contract, commit e6f166d3)**: the
default fake-review result is REQUEST_CHANGES, which causes a loop-back without
a merge.  The ledger therefore survives for inspection after ``run_pipeline``
returns.  This avoids the need for a pre-clear observer while fully exercising
the real triage/plan boundary recording.  The scenario scripts the review
explicitly to REQUEST_CHANGES so this assumption is never implicit.
"""

from __future__ import annotations

import pytest

from models import ReviewVerdict
from tests.conftest import ReviewResultFactory
from tests.scenarios.builders import IssueBuilder
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Helper — copied verbatim from test_convergence_review_mockworld.py
# (replicating the small local helper is intentional per the task brief;
#  do not refactor the existing file)
# ---------------------------------------------------------------------------


def _make_world_with_gate(tmp_path, *, max_convergence_laps: int = 3) -> MockWorld:
    """Return a fresh MockWorld for convergence-gate scenarios.

    The convergence gate is unconditional: boundary recording and the
    HybridGate decision path are always-on, so no flag toggle is needed.
    We pass a config built before constructing MockWorld so that
    ``ReviewPhase`` (wired in ``PipelineHarness.__init__``) picks up
    ``max_convergence_laps`` at construction time.
    """
    from tests.helpers import ConfigFactory

    cfg = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        max_workers=1,
        max_planners=1,
        max_reviewers=1,
        visual_validation_enabled=False,
        max_ci_fix_attempts=0,
    )
    cfg.max_convergence_laps = max_convergence_laps
    return MockWorld(tmp_path, config=cfg)


# ---------------------------------------------------------------------------
# Scenario — pipeline-level boundary recording (triage + plan)
# ---------------------------------------------------------------------------


class TestPipelineBoundaryRecording:
    """Gate ON: full pipeline run records triage and plan boundary verdicts.

    This is the integration-level proof that the boundary recording added in
    Tasks 2–4 fires through the REAL triage and plan phase code inside
    MockWorld.

    The review is scripted to REQUEST_CHANGES (loop-back, no merge).  This is
    the key adaptation for the clear-on-merge contract (commit e6f166d3): when
    the pipeline ends with a merge the ledger is immediately cleared, making
    post-run ledger inspection impossible without an observer.  By scripting a
    REQUEST_CHANGES verdict the pipeline loops back instead of merging, so the
    ledger is intact for the ``stage_state`` assertions.  The purpose of the
    test is fully preserved: the real triage/plan boundary recording ran through
    MockWorld, recording ADVANCE for both stages, as confirmed by the ledger.
    The review boundary (LOOP_BACK) is also reflected in ``stage_state``.

    The test drives issue #1 through the full pipeline and asserts:

    - ``stage_state["triage"].last_verdict == "ADVANCE"`` — real triage ran.
    - ``stage_state["plan"].last_verdict == "ADVANCE"`` — real plan ran.
    - Issue is NOT merged (loop-back; ledger survives for inspection).

    Note: ``run_pipeline`` does NOT include a shape phase; do not assert on
    ``"shape"``.  The pipeline order is triage → plan → implement → review.
    This scenario complements ``test_convergence_review_mockworld.py``, which
    covers the gated APPROVE path.
    """

    async def test_pipeline_records_triage_and_plan_verdicts(self, tmp_path) -> None:
        """Full gated pipeline populates ledger with ADVANCE for triage and plan.

        Review is scripted to REQUEST_CHANGES (loop-back, no merge) so the ledger
        survives for inspection post-run.  The triage/plan ADVANCE verdicts are
        the load-bearing assertions; the review loop-back is a side effect.
        """
        world = _make_world_with_gate(tmp_path)

        IssueBuilder().numbered(1).titled("Add feature").bodied(
            "Implement a feature"
        ).at(world)

        # Script a REQUEST_CHANGES verdict so the pipeline loops back without
        # merging.  This prevents clear_convergence_ledger from wiping the ledger
        # before we can assert on triage/plan stage_state entries.
        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world.set_phase_results("review", 1, [reject])

        result = await world.run_pipeline()

        # --- non-vacuity probe ---
        # If this fails, the real triage/plan boundary recording did not run
        # through MockWorld — a wiring regression, not a vacuous pass.
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated pipeline run ending in "
            "REQUEST_CHANGES loop-back — the real triage/plan boundary recording "
            "did not run through MockWorld."
        )

        # Issue looped back (not merged).
        outcome = result.issue(1)
        assert outcome.merged is False, (
            "Expected issue #1 to remain un-merged after REQUEST_CHANGES loop-back; "
            f"got merged={outcome.merged!r}"
        )

        # --- triage boundary ---
        triage_rec = ledger.stage_state.get("triage")
        assert triage_rec is not None, "triage boundary did not record into the ledger"
        assert triage_rec.last_verdict == "ADVANCE", (
            f"expected triage ADVANCE (routed to plan); got {triage_rec.last_verdict}"
        )

        # --- plan boundary ---
        plan_rec = ledger.stage_state.get("plan")
        assert plan_rec is not None, "plan boundary did not record into the ledger"
        assert plan_rec.last_verdict == "ADVANCE", (
            f"expected plan ADVANCE (plan succeeded); got {plan_rec.last_verdict}"
        )
