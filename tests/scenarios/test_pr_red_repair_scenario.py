"""MockWorld scenario for PrRedRepairLoop (#10027 Phase 1: infra-flake retrier).

Two scenarios over FakeGitHub end-to-end:

* ``test_settled_red_pr_gets_bounded_rerun`` — a PR whose only failing
  check is a cancelled job (an infra-flake signature) settles red; the
  loop must trigger ``gh run rerun --failed`` on that run exactly once
  and bump the PR's attempt counter, without touching a second PR whose
  CI is still green.

* ``test_mid_rerun_stale_conclusion_then_settles_red_again`` — the
  #10027 trap, pinned end-to-end: tick 1 reruns a cancelled run (attempt
  1). Tick 2 simulates the run mid-rerun (status flips to in_progress
  while the job record still carries the stale FAILURE conclusion from
  before) — the loop must NOT fire a second rerun while pending. Tick 3
  simulates the rerun completing red again (status back to completed) —
  the loop fires bounded rerun attempt 2, still within the configured
  cap.

``config.pr_red_repair_loop_enabled`` is a static-config gate (default
True) but the scenario constructs the loop directly, matching
SandboxFailureFixerLoop's scenario pattern — the catalog builder has no
per-scenario config-enable seam.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _make_state(attempts: dict[int, int] | None = None) -> MagicMock:
    """State mock mirroring PrRedRepairStateMixin + RollupIssueStateMixin."""
    state = MagicMock()
    counts: dict[str, int] = {str(k): v for k, v in (attempts or {}).items()}

    def _get(pr_number: int) -> int:
        return int(counts.get(str(pr_number), 0))

    def _bump(pr_number: int) -> int:
        new = _get(pr_number) + 1
        counts[str(pr_number)] = new
        return new

    state.get_pr_red_rerun_attempts.side_effect = _get
    state.bump_pr_red_rerun_attempts.side_effect = _bump
    state.get_rollup_issue.return_value = None
    state.get_rollup_issue_keys.return_value = []
    state._counts = counts
    return state


def _build_loop(tmp_path, github, state, **config_overrides):
    from pr_red_repair_loop import PrRedRepairLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path, **config_overrides)
    # pr_red_repair_loop_enabled defaults True in production config but
    # isn't in ConfigFactory's enumerated kwargs — set it directly on the
    # frozen config, mirroring test_gate_health_loop.py's pattern.
    object.__setattr__(bg.config, "pr_red_repair_loop_enabled", True)
    return PrRedRepairLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        deps=bg.loop_deps,
    )


class TestPrRedRepairScenario:
    """#10027 Phase 1 — settled-red detection + bounded infra-flake rerun."""

    async def test_settled_red_pr_gets_bounded_rerun(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        github = world.github

        github.add_pr(number=42, issue_number=10, branch="feat/flaky")
        github.add_pr(number=43, issue_number=11, branch="feat/clean")

        github.add_workflow_run(
            run_id=555,
            workflow="CI",
            conclusion="cancelled",
            pr_number=42,
            created_at="2026-07-20T00:00:00Z",
            jobs=[
                {
                    "name": "Tests",
                    "status": "completed",
                    "conclusion": "cancelled",
                    "steps": [],
                }
            ],
        )
        github.add_workflow_run(
            run_id=556,
            workflow="CI",
            conclusion="success",
            pr_number=43,
            created_at="2026-07-20T00:00:00Z",
            jobs=[
                {
                    "name": "Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [],
                }
            ],
        )

        state = _make_state()
        loop = _build_loop(tmp_path, github, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["reran"] == 1
        assert result["escalated"] == 0
        assert github._workflow_reruns == [555]
        assert state._counts == {"42": 1}

    async def test_mid_rerun_stale_conclusion_then_settles_red_again(
        self, tmp_path
    ) -> None:
        """PINNED (#10027): a stale FAILURE conclusion during an in-flight
        rerun must never double-fire; once the rerun genuinely completes
        red, the NEXT bounded attempt fires normally."""
        world = MockWorld(tmp_path)
        github = world.github
        github.add_pr(number=42, issue_number=10, branch="feat/flaky")

        github.add_workflow_run(
            run_id=555,
            workflow="CI",
            conclusion="cancelled",
            pr_number=42,
            created_at="2026-07-20T00:00:00Z",
            jobs=[
                {
                    "name": "Tests",
                    "status": "completed",
                    "conclusion": "cancelled",
                    "steps": [],
                }
            ],
        )

        state = _make_state()
        loop = _build_loop(tmp_path, github, state)

        # Tick 1: settled-red (cancelled) -> bounded rerun attempt 1.
        result_1 = await loop._do_work()
        assert result_1["reran"] == 1
        assert github._workflow_reruns == [555]
        assert state._counts == {"42": 1}

        # Tick 2: rerun in flight. The rollup's job entry keeps the OLD
        # (pre-rerun) FAILURE conclusion while status has already flipped
        # back to in_progress — the exact trap hit twice on 2026-07-19/20.
        github._workflow_jobs[555] = [
            {
                "name": "Tests",
                "status": "in_progress",
                "conclusion": "failure",
                "steps": [],
            }
        ]
        result_2 = await loop._do_work()
        assert result_2["status"] == "ok"
        assert result_2["reran"] == 0
        assert result_2["escalated"] == 0
        # No second rerun call was made while the run was still pending.
        assert github._workflow_reruns == [555]
        assert state._counts == {"42": 1}

        # Tick 3: the rerun finishes — genuinely red again (a fresh
        # cancellation this time). Bounded attempt 2 fires (cap is 2).
        github._workflow_jobs[555] = [
            {
                "name": "Tests",
                "status": "completed",
                "conclusion": "cancelled",
                "steps": [],
            }
        ]
        result_3 = await loop._do_work()
        assert result_3["reran"] == 1
        assert result_3["escalated"] == 0
        assert github._workflow_reruns == [555, 555]
        assert state._counts == {"42": 2}

        # Tick 4: still red, but the 2-attempt cap (default) is now spent
        # -> escalate via rollup issue instead of a third rerun.
        result_4 = await loop._do_work()
        assert result_4["reran"] == 0
        assert result_4["escalated"] == 1
        assert github._workflow_reruns == [555, 555]
