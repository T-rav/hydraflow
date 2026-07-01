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
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Helper — copied verbatim from test_convergence_review_mockworld.py
# (replicating the small local helper is intentional per the task brief;
#  do not refactor the existing file)
# ---------------------------------------------------------------------------


def _make_world_with_gate(tmp_path, *, max_convergence_laps: int = 3) -> MockWorld:
    """Return a fresh MockWorld with the convergence gate enabled.

    We pass a config built before constructing MockWorld so that
    ``ReviewPhase`` (wired in ``PipelineHarness.__init__``) picks up the flag
    at construction time.  Mutating ``world.harness.config`` after the fact
    would also work because ``ReviewPhase`` reads ``convergence_gate_enabled``
    from config, but passing it in at construction is the cleaner contract.
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
    cfg.convergence_gate_enabled = True
    cfg.max_convergence_laps = max_convergence_laps
    return MockWorld(tmp_path, config=cfg)


# ---------------------------------------------------------------------------
# Scenario — pipeline-level boundary recording (triage + plan)
# ---------------------------------------------------------------------------


class TestPipelineBoundaryRecording:
    """Gate ON: full pipeline run records triage and plan boundary verdicts.

    This is the integration-level proof that the boundary recording added in
    Tasks 2–4 fires through the REAL triage and plan phase code inside
    MockWorld.  No LLM scripting is required: the default fakes route triage
    to ``"plan"`` (which maps to ``"ADVANCE"`` via ``_TRIAGE_VERDICT_MAP``)
    and plan succeeds (``ts_status=="success"`` → ``"ADVANCE"``).

    The test drives issue #1 through the full pipeline, then inspects the
    convergence ledger to confirm both boundaries recorded ``ADVANCE`` without
    any hand-population of the ledger.

    Note: ``run_pipeline`` does NOT include a shape phase; do not assert on
    ``"shape"``.  The pipeline order is triage → plan → implement → review.
    This scenario complements ``test_convergence_review_mockworld.py``, which
    covers the review boundary.
    """

    async def test_pipeline_records_triage_and_plan_verdicts(self, tmp_path) -> None:
        """Full gated pipeline populates ledger with ADVANCE for triage and plan."""
        world = _make_world_with_gate(tmp_path)

        IssueBuilder().numbered(1).titled("Add feature").bodied(
            "Implement a feature"
        ).at(world)

        await world.run_pipeline()

        # --- non-vacuity probe ---
        # If this fails, the real triage/plan boundary recording did not run
        # through MockWorld — a wiring regression, not a vacuous pass.
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated full pipeline run — the real "
            "triage/plan boundary recording did not run through MockWorld."
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
