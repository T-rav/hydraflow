"""End-to-end bead workflow scenarios using FakeBeads.

Prod-code bead lifecycle
------------------------
- **Implement phase** (`implement_phase._create_beads_in_worktree`): reads the
  plan (the issue's "## Implementation Plan" comment, or plans_dir/issue-N.md),
  calls ``extract_phases``; if phases are found it inits beads in THIS worktree
  and calls ``create_from_phases`` (one bead per phase + dependency wiring),
  stores the ``{phase_id: bead_id}`` mapping via ``set_bead_mapping`` and passes
  it to the agent. The mapping is informational to the agent: factory prompts
  prohibit the database-backed CLI. Production claims root tasks before the
  run and, only after a verified success, claims and closes each ready frontier
  through the direct JSONL manager API. Failure closes nothing.
- **Plan phase**: does NOT create beads (moved to implement phase).
- **Review phase** (`review_phase.py`): reads the mapping from state and builds
  a ``bead_tasks`` context list (hardcoded ``status='closed'`` — an assumption,
  not a real query).  No ``BeadsManager`` methods are called.

The plan text **must** contain phase headers matching the regex
``### P{N} — Name`` for ``extract_phases`` to return phases.  The default
``PlanResultFactory`` plan string does NOT contain these headers, so the plan
must be explicitly set.
"""

from __future__ import annotations

import json

import pytest

from mockworld.fakes.fake_beads import FakeBeads
from tests.conftest import PlanResultFactory, WorkerResultFactory
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario

# ---------------------------------------------------------------------------
# A valid Task Graph plan — two phases with a dependency chain.
# extract_phases() requires "### P{N} — <name>" headers.
# ---------------------------------------------------------------------------
_TASK_GRAPH_PLAN = """\
## Plan

Add feature X in two phases.

## Task Graph

### P1 — Data model
**Files:** src/models.py
**Tests:**
- model fields are correct
**Depends on:** none

### P2 — API endpoint
**Files:** src/api.py
**Tests:**
- endpoint returns 200
**Depends on:** P1
"""


async def test_B1_bead_workflow_end_to_end(tmp_path) -> None:
    """Plan creates beads → implement init fires → bead mapping in state.

    Pipeline bead behaviour (matched to prod reality):

    1. FakeBeads is wired into MockWorld/PipelineHarness.
    2. Implement phase detects Task Graph phases in the plan text and calls
       ``create_from_phases`` → one bead per phase is stored in FakeBeads.
    3. Implement phase calls ``beads_manager.init`` (because a bead mapping
       now exists in state).
    4. The factory claims P1 before the run. On verified success it closes P1,
       then claims and closes newly ready P2.
    5. Review phase reads the mapping from state but calls no FakeBeads
       methods, so bead state is unchanged.

    If any of the three invariants above break, the corresponding assertion
    fails with a diagnostic message pointing to the relevant prod-code site.
    """
    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)
    world.add_issue(1, "add feature X", "body", labels=["hydraflow-ready"])

    # Beads are now created by the IMPLEMENT phase in its own worktree, reading
    # the plan from plans_dir/issue-N.md (written by the planner in prod via
    # planner._save_plan). Seed it so the implement phase finds the task graph.
    plans_dir = world.harness.config.plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "issue-1.md").write_text(_TASK_GRAPH_PLAN)

    # Provide a plan whose text contains Task Graph phase headers.
    plan = PlanResultFactory.create(
        issue_number=1,
        success=True,
        plan=_TASK_GRAPH_PLAN,
    )
    world._llm.script_plan(1, [plan])

    result = await world.run_pipeline()

    # ------------------------------------------------------------------
    # Assertion 1: FakeBeads was initialised by the implement phase.
    # Triggered by implement_phase._create_beads_in_worktree when the plan has
    # a task graph. If False, the implementer did not find a plan / phases.
    # ------------------------------------------------------------------
    assert beads._initialized is True, (
        "FakeBeads.init was never called — the implementer inits beads in its "
        "worktree only when it extracts task-graph phases from the plan "
        "(implement_phase._create_beads_in_worktree). Check the seeded plan."
    )

    # ------------------------------------------------------------------
    # Assertion 2: Two beads were created (one per Task Graph phase).
    # Triggered by implement_phase._create_beads_in_worktree via
    # create_from_phases. The plan above has two P{N} headers → two phases.
    # ------------------------------------------------------------------
    assert beads.task_count() == 2, (
        f"Expected 2 bead tasks (one per plan phase), got {beads.task_count()}. "
        "implement_phase._create_beads_in_worktree calls create_from_phases "
        "only when extract_phases finds '### P{N} — Name' headers."
    )

    # ------------------------------------------------------------------
    # Assertion 3: Dependency wiring — P2 depends on P1.
    # FakeBeads.add_dependency records the edge; verify by inspecting the
    # internal _tasks dict.  P2 is the second bead created (bd-fake-2).
    # ------------------------------------------------------------------
    task_ids = beads.task_ids()
    assert len(task_ids) == 2  # matches A2
    p1_bead_id, p2_bead_id = task_ids[0], task_ids[1]
    p2_internal = beads._tasks[p2_bead_id]
    assert p1_bead_id in p2_internal.depends_on, (
        f"P2 bead ({p2_bead_id}) should depend on P1 bead ({p1_bead_id}). "
        f"Actual depends_on: {p2_internal.depends_on}"
    )

    # ------------------------------------------------------------------
    # Assertion 4: The successful graph advances in dependency order and every
    # task passes through claim before close.
    # ------------------------------------------------------------------
    assert beads.transitions == [
        ("claim", p1_bead_id),
        ("close", p1_bead_id),
        ("claim", p2_bead_id),
        ("close", p2_bead_id),
    ]
    assert {task.status for task in beads._tasks.values()} == {"closed"}

    # The scenario observes the actual production-format worktree store, not
    # merely the fake's cache. Stable refs/dependencies survive and the exact
    # bytes captured at commit_pending already contain the finalized lifecycle,
    # proving persistence happens after every claim/close transition.
    issues_path = tmp_path / "worktrees" / "issue-1" / ".beads" / "issues.jsonl"
    persisted = [json.loads(line) for line in issues_path.read_text().splitlines()]
    assert {record["status"] for record in persisted} == {"closed"}
    assert {record["external_ref"] for record in persisted} == {
        "hydraflow-factory:issue:1:phase:P1",
        "hydraflow-factory:issue:1:phase:P2",
    }
    p2_record = next(record for record in persisted if record["id"] == p2_bead_id)
    assert p2_record["dependencies"][0]["depends_on_id"] == p1_bead_id
    assert world._llm.agents.commit_pending_snapshots == [(1, issues_path.read_bytes())]

    # ------------------------------------------------------------------
    # Assertion 5: Pipeline completed (issue is tracked in result).
    # ------------------------------------------------------------------
    assert result.issue(1) is not None, "Pipeline returned no outcome for issue #1"


async def test_B1_no_beads_without_task_graph_headers(tmp_path) -> None:
    """Plan text without Task Graph headers → no beads created, no crash.

    Validates the guard at plan_phase.py:401 — if extract_phases returns []
    the method returns early; FakeBeads.create_from_phases is never called so
    task_count() stays at 0 and _initialized stays False.
    """
    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)
    world.add_issue(2, "plain task", "body", labels=["hydraflow-ready"])

    # Default plan text — no "### P{N} — ..." headers → extract_phases → []
    plain_plan = PlanResultFactory.create(
        issue_number=2,
        success=True,
        plan="## Plan\n\n1. Do the thing\n2. Test the thing",
    )
    world._llm.script_plan(2, [plain_plan])

    result = await world.run_pipeline()

    # No phases → no beads → no init
    assert beads.task_count() == 0, (
        "Expected 0 beads when plan text has no Task Graph headers. "
        f"Got {beads.task_count()} — check plan_phase._create_beads_from_plan."
    )
    assert beads._initialized is False, (
        "FakeBeads.init should not be called when no bead mapping was stored. "
        "implement_phase.py:577 gates init on get_bead_mapping returning truthy."
    )
    assert result.issue(2) is not None, "Pipeline returned no outcome for issue #2"


async def test_B2_failed_run_does_not_close_unfinished_phases(tmp_path) -> None:
    """A failed run leaves the active root claimed and its dependent open."""
    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)
    world.add_issue(1, "add feature X", "body", labels=["hydraflow-ready"])

    plans_dir = world.harness.config.plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "issue-1.md").write_text(_TASK_GRAPH_PLAN)
    world._llm.script_plan(
        1,
        [
            PlanResultFactory.create(
                issue_number=1,
                success=True,
                plan=_TASK_GRAPH_PLAN,
            )
        ],
    )

    world.set_phase_result(
        "implement",
        1,
        WorkerResultFactory.create(
            issue_number=1,
            success=False,
            commits=0,
            error="implementation interrupted",
        ),
    )

    result = await world.run_pipeline()

    p1_bead_id, p2_bead_id = beads.task_ids()
    assert beads.transitions == [("claim", p1_bead_id)]
    assert beads._tasks[p1_bead_id].status == "in_progress"
    assert beads._tasks[p2_bead_id].status == "open"
    persisted = [
        json.loads(line)
        for line in (tmp_path / "worktrees" / "issue-1" / ".beads" / "issues.jsonl")
        .read_text()
        .splitlines()
    ]
    assert {record["id"]: record["status"] for record in persisted} == {
        p1_bead_id: "in_progress",
        p2_bead_id: "open",
    }
    assert world._llm.agents.commit_pending_snapshots == []
    assert not result.issue(1).merged


async def test_B3_finalized_jsonl_commit_failure_blocks_pipeline_success(
    tmp_path,
) -> None:
    """A failed persistence boundary prevents a PR after lifecycle finalization."""
    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)
    world.add_issue(1, "add feature X", "body", labels=["hydraflow-ready"])
    plans_dir = world.harness.config.plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "issue-1.md").write_text(_TASK_GRAPH_PLAN)
    world._llm.script_plan(
        1,
        [
            PlanResultFactory.create(
                issue_number=1,
                success=True,
                plan=_TASK_GRAPH_PLAN,
            )
        ],
    )
    world._llm.agents.fail_next_commit_pending()

    result = await world.run_pipeline()

    issues_path = tmp_path / "worktrees" / "issue-1" / ".beads" / "issues.jsonl"
    persisted = [json.loads(line) for line in issues_path.read_text().splitlines()]
    assert {record["status"] for record in persisted} == {"closed"}
    assert world._llm.agents.commit_pending_snapshots == [(1, issues_path.read_bytes())]
    assert not result.issue(1).merged
