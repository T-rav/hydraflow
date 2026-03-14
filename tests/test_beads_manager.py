"""Tests for the BeadsManager — bd CLI wrapper and integration points."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from beads_manager import BeadsManager, BeadTask
from task_graph import TaskGraphPhase


@pytest.fixture()
def _enabled_config():
    """Return a mock config with beads_enabled=True."""
    cfg = AsyncMock()
    cfg.beads_enabled = True
    return cfg


@pytest.fixture()
def _disabled_config():
    """Return a mock config with beads_enabled=False."""
    cfg = AsyncMock()
    cfg.beads_enabled = False
    return cfg


@pytest.fixture()
def manager(_enabled_config):
    return BeadsManager(_enabled_config)


@pytest.fixture()
def disabled_manager(_disabled_config):
    return BeadsManager(_disabled_config)


# ---------------------------------------------------------------------------
# No-op when disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_disabled_is_available(disabled_manager):
    assert await disabled_manager.is_available() is False


@pytest.mark.asyncio()
async def test_disabled_init(disabled_manager):
    assert await disabled_manager.init(Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_create_task(disabled_manager):
    assert await disabled_manager.create_task("title", "0", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_add_dependency(disabled_manager):
    assert (
        await disabled_manager.add_dependency("bd-a1", "bd-b2", Path("/tmp")) is False
    )


@pytest.mark.asyncio()
async def test_disabled_claim(disabled_manager):
    assert await disabled_manager.claim("bd-a1", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_close(disabled_manager):
    assert await disabled_manager.close("bd-a1", "done", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_list_ready(disabled_manager):
    assert await disabled_manager.list_ready(Path("/tmp")) == []


@pytest.mark.asyncio()
async def test_disabled_show(disabled_manager):
    assert await disabled_manager.show("bd-a1", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_create_from_phases(disabled_manager):
    phases = [
        TaskGraphPhase(id="P1", name="P1 — Setup", files=[], tests=[], depends_on=[])
    ]
    assert await disabled_manager.create_from_phases(phases, 42, Path("/tmp")) == {}


# ---------------------------------------------------------------------------
# is_available — uses `bd ready` as a liveness check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_is_available_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = ""
        assert await manager.is_available() is True
        mock_run.assert_called_once_with("bd", "ready", timeout=10.0)


@pytest.mark.asyncio()
async def test_is_available_not_installed(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("bd not found")
        assert await manager.is_available() is False


@pytest.mark.asyncio()
async def test_is_available_runtime_error(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("command failed")
        assert await manager.is_available() is False


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Initialized"
        assert await manager.init(Path("/repo")) is True
        mock_run.assert_called_once_with("bd", "init", cwd=Path("/repo"), timeout=30.0)


@pytest.mark.asyncio()
async def test_init_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.init(Path("/repo")) is False


# ---------------------------------------------------------------------------
# create_task — uses `bd create "title" -p <priority>`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_hash_id(manager):
    """bd create returns hash-based IDs like bd-a1b2."""
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Created bd-a1b2"
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result == "bd-a1b2"
        mock_run.assert_called_once_with(
            "bd", "create", "My task", "-p", "0", cwd=Path("/repo"), timeout=30.0
        )


@pytest.mark.asyncio()
async def test_create_task_hierarchical_id(manager):
    """bd can return hierarchical IDs like bd-a3f8.1.1."""
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Created bd-a3f8.1.1"
        result = await manager.create_task("Sub-task", "1", Path("/repo"))
        assert result == "bd-a3f8.1.1"


@pytest.mark.asyncio()
async def test_create_task_numeric_fallback(manager):
    """Falls back to numeric ID parsing if hash format not found."""
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Created task #42"
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result == "42"


@pytest.mark.asyncio()
async def test_create_task_no_id_in_output(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Something unexpected with no ids"
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result is None


@pytest.mark.asyncio()
async def test_create_task_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result is None


# ---------------------------------------------------------------------------
# add_dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Dependency added"
        assert await manager.add_dependency("bd-b2", "bd-a1", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd", "dep", "add", "bd-b2", "bd-a1", cwd=Path("/repo"), timeout=30.0
        )


@pytest.mark.asyncio()
async def test_add_dependency_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.add_dependency("bd-b2", "bd-a1", Path("/repo")) is False


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Claimed"
        assert await manager.claim("bd-a1b2", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd", "update", "bd-a1b2", "--claim", cwd=Path("/repo"), timeout=30.0
        )


@pytest.mark.asyncio()
async def test_claim_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = OSError("disk error")
        assert await manager.claim("bd-a1b2", Path("/repo")) is False


# ---------------------------------------------------------------------------
# close — uses `bd close <id> "message"` (positional, no --reason flag)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_close_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Closed"
        assert await manager.close("bd-a1b2", "Phase complete", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd", "close", "bd-a1b2", "Phase complete", cwd=Path("/repo"), timeout=30.0
        )


@pytest.mark.asyncio()
async def test_close_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.close("bd-a1b2", "done", Path("/repo")) is False


# ---------------------------------------------------------------------------
# list_ready — uses `bd ready --json`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_ready_hash_ids(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (
            "bd-a1b2 My task [open]\nbd-c3d4 Another task [in_progress]\n"
        )
        result = await manager.list_ready(Path("/repo"))
        assert len(result) == 2
        assert result[0].id == "bd-a1b2"
        assert result[0].title == "My task"
        assert result[0].status == "open"
        assert result[1].id == "bd-c3d4"
        assert result[1].status == "in_progress"
        mock_run.assert_called_once_with(
            "bd", "ready", "--json", cwd=Path("/repo"), timeout=30.0
        )


@pytest.mark.asyncio()
async def test_list_ready_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.list_ready(Path("/repo")) == []


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_show_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (
            "Title: My task\n"
            "Status: in_progress\n"
            "Priority: 0\n"
            "Depends on: bd-a1f0, bd-b2e1\n"
        )
        result = await manager.show("bd-a1b2", Path("/repo"))
        assert result is not None
        assert result.id == "bd-a1b2"
        assert result.title == "My task"
        assert result.status == "in_progress"
        assert result.priority == "0"
        assert result.depends_on == ["bd-a1f0", "bd-b2e1"]


@pytest.mark.asyncio()
async def test_show_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("not found")
        assert await manager.show("bd-a1b2", Path("/repo")) is None


# ---------------------------------------------------------------------------
# create_from_phases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_from_phases(manager):
    phases = [
        TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/model.py"],
            tests=["test model creation"],
            depends_on=[],
        ),
        TaskGraphPhase(
            id="P2",
            name="P2 — API Layer",
            files=["src/api.py"],
            tests=["test api endpoint"],
            depends_on=["P1"],
        ),
    ]

    call_count = 0

    async def mock_run(*args, **_kwargs):
        nonlocal call_count
        call_count += 1
        cmd_args = list(args)
        if "create" in cmd_args:
            return f"Created bd-{'a' * call_count}{call_count}"
        if "dep" in cmd_args:
            return "Dependency added"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert "P1" in mapping
    assert "P2" in mapping
    assert len(mapping) == 2
    # P1 has no deps → priority 0, P2 has deps → priority 1
    create_calls = [c for c in mock_run_fn.call_args_list if "create" in list(c.args)]
    assert create_calls[0].args[4] == "0"  # -p 0 for P1
    assert create_calls[1].args[4] == "1"  # -p 1 for P2


@pytest.mark.asyncio()
async def test_create_from_phases_partial_failure(manager):
    """Partial failures during bead creation are handled gracefully."""
    phases = [
        TaskGraphPhase(id="P1", name="P1 — Model", files=[], tests=[], depends_on=[]),
        TaskGraphPhase(id="P2", name="P2 — API", files=[], tests=[], depends_on=["P1"]),
    ]

    async def mock_run(*args, **_kwargs):
        cmd_args = list(args)
        if "create" in cmd_args and "P2" in str(cmd_args):
            raise RuntimeError("failed")
        if "create" in cmd_args:
            return "Created bd-ok1"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert "P1" in mapping
    assert "P2" not in mapping


# ---------------------------------------------------------------------------
# _parse_task_list
# ---------------------------------------------------------------------------


def test_parse_task_list_empty():
    assert BeadsManager._parse_task_list("") == []


def test_parse_task_list_hash_ids():
    output = "bd-a1b2 Task A [open]\nbd-c3d4 Task B [closed]\n"
    tasks = BeadsManager._parse_task_list(output)
    assert len(tasks) == 2
    assert tasks[0] == BeadTask(id="bd-a1b2", title="Task A", status="open")
    assert tasks[1] == BeadTask(id="bd-c3d4", title="Task B", status="closed")


def test_parse_task_list_numeric_fallback():
    output = "#1 Task A [open]\n#2 Task B [closed]\n"
    tasks = BeadsManager._parse_task_list(output)
    assert len(tasks) == 2
    assert tasks[0].id == "1"
    assert tasks[1].id == "2"


def test_parse_task_list_skips_junk_lines():
    output = "Some header\n\nbd-a1b2 Real task [open]\n---\n"
    tasks = BeadsManager._parse_task_list(output)
    assert len(tasks) == 1
    assert tasks[0].id == "bd-a1b2"


# ---------------------------------------------------------------------------
# _parse_show_output
# ---------------------------------------------------------------------------


def test_parse_show_output_hash_deps():
    output = (
        "Title: Test task\nStatus: open\nPriority: 0\nDepends on: bd-a1f0, bd-b2e1\n"
    )
    task = BeadsManager._parse_show_output("bd-a1b2", output)
    assert task.id == "bd-a1b2"
    assert task.title == "Test task"
    assert task.depends_on == ["bd-a1f0", "bd-b2e1"]


def test_parse_show_output_minimal():
    task = BeadsManager._parse_show_output("bd-a1b2", "")
    assert task.id == "bd-a1b2"
    assert task.title == "Bead bd-a1b2"


# ---------------------------------------------------------------------------
# State roundtrip
# ---------------------------------------------------------------------------


def test_bead_mapping_state_roundtrip(tmp_path):
    """Verify bead mappings survive a state save/load cycle."""
    from state import StateTracker

    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)

    mapping = {"P1": "bd-a1b2", "P2": "bd-c3d4", "P3": "bd-e5f6"}
    tracker.set_bead_mapping(42, mapping)

    assert tracker.get_bead_mapping(42) == mapping
    assert tracker.get_bead_mapping(999) == {}

    # Reload from disk
    tracker2 = StateTracker(state_file)
    assert tracker2.get_bead_mapping(42) == mapping


# ===========================================================================
# Integration tests — plan_phase._create_beads_from_plan
# ===========================================================================

_TASK_GRAPH_PLAN = (
    "## Task Graph\n\n"
    "### P1 \u2014 Model\n"
    "**Files:** src/models.py\n"
    "**Tests:**\n- Widget persists\n"
    "**Depends on:** (none)\n\n"
    "### P2 \u2014 API\n"
    "**Files:** src/api.py\n"
    "**Tests:**\n- GET returns list\n"
    "**Depends on:** P1\n"
)


class TestPlanPhaseBeadsIntegration:
    """Tests for beads creation during the plan phase."""

    @pytest.mark.asyncio()
    async def test_handle_plan_success_creates_beads_when_enabled(self, config) -> None:
        """After a successful plan with Task Graph, beads are created and mapping posted."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)

        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        mock_beads.create_from_phases = AsyncMock(
            return_value={"P1": "bd-a1b2", "P2": "bd-c3d4"}
        )
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        # BeadsManager was called correctly
        mock_beads.init.assert_awaited_once()
        mock_beads.create_from_phases.assert_awaited_once()
        call_args = mock_beads.create_from_phases.call_args
        phases_arg = call_args.args[0]
        assert len(phases_arg) == 2
        assert call_args.args[1] == 42

        # Mapping saved to state
        assert state.get_bead_mapping(42) == {"P1": "bd-a1b2", "P2": "bd-c3d4"}

        # Mapping table posted as comment
        bead_comments = [
            c for c in prs.post_comment.call_args_list if "Bead Task Mapping" in str(c)
        ]
        assert len(bead_comments) == 1
        comment_body = bead_comments[0].args[1]
        assert "| P1 | #bd-a1b2 |" in comment_body
        assert "| P2 | #bd-c3d4 |" in comment_body

    @pytest.mark.asyncio()
    async def test_handle_plan_success_skips_beads_when_disabled(self, config) -> None:
        """When beads_manager is None, no bead creation occurs."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        assert state.get_bead_mapping(42) == {}

    @pytest.mark.asyncio()
    async def test_beads_skipped_when_plan_has_no_task_graph(self, config) -> None:
        """Plans without Task Graph phases produce no beads even when enabled."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(
            success=True, plan="## Plan\n\n1. Do the thing\n2. Test it\n"
        )
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        mock_beads.init.assert_not_awaited()
        mock_beads.create_from_phases.assert_not_awaited()
        assert state.get_bead_mapping(42) == {}

    @pytest.mark.asyncio()
    async def test_beads_empty_mapping_not_saved(self, config) -> None:
        """When create_from_phases returns empty mapping, nothing is saved."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        mock_beads.create_from_phases = AsyncMock(return_value={})
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        assert state.get_bead_mapping(42) == {}
        bead_comments = [
            c for c in prs.post_comment.call_args_list if "Bead Task Mapping" in str(c)
        ]
        assert len(bead_comments) == 0

    @pytest.mark.asyncio()
    async def test_comment_post_failure_does_not_crash(self, config) -> None:
        """If posting the bead mapping comment fails, the plan still succeeds."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        mock_beads.create_from_phases = AsyncMock(return_value={"P1": "bd-a1b2"})
        phase._beads_manager = mock_beads

        # Make post_comment raise on bead mapping comments
        original_post = prs.post_comment

        async def selective_fail(issue_id, body, *args, **kwargs):
            if "Bead Task Mapping" in body:
                raise RuntimeError("GitHub API error")
            return await original_post(issue_id, body, *args, **kwargs)

        prs.post_comment = AsyncMock(side_effect=selective_fail)

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        # Should not raise
        results = await phase.plan_issues()

        # Mapping was still saved despite comment failure
        assert state.get_bead_mapping(42) == {"P1": "bd-a1b2"}
        # Plan still succeeded
        assert len(results) == 1


# ===========================================================================
# Integration tests — agent._build_tdd_subagent_plan with bead_mapping
# ===========================================================================


class TestAgentBeadPromptIntegration:
    """Tests for bead lifecycle injection into TDD sub-agent prompts."""

    def test_bead_mapping_injects_claim_and_close(self, config, event_bus) -> None:
        """When bead_mapping is provided, claim/close commands appear in prompt."""
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "bd-a1b2", "P2": "bd-c3d4"}
        )

        # Bead headers present
        assert "**Bead:** #bd-a1b2" in prompt
        assert "**Bead:** #bd-c3d4" in prompt

        # Claim commands (--claim flag is correct per bd CLI)
        assert "bd update bd-a1b2 --claim" in prompt
        assert "bd update bd-c3d4 --claim" in prompt

        # Close commands (positional message, no --reason flag)
        assert 'bd close bd-a1b2 "Phase complete"' in prompt
        assert 'bd close bd-c3d4 "Phase complete"' in prompt

        # Verify no --reason flag
        assert "--reason" not in prompt

    def test_no_bead_mapping_no_bead_commands(self, config, event_bus) -> None:
        """Without bead_mapping, no bd commands appear in the prompt."""
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue, bead_mapping=None)

        assert "bd update" not in prompt
        assert "bd close" not in prompt
        assert "**Bead:**" not in prompt

    def test_partial_bead_mapping(self, config, event_bus) -> None:
        """Only phases with bead IDs get lifecycle commands."""
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "bd-a1b2"}
        )

        assert "**Bead:** #bd-a1b2" in prompt
        assert "bd update bd-a1b2 --claim" in prompt
        # P2 should NOT have bead commands
        assert "bd-c3d4" not in prompt


# ===========================================================================
# Integration tests — implement_phase passes bead_mapping to agent
# ===========================================================================


class TestImplementPhaseBeadsIntegration:
    """Tests for bead mapping passthrough in the implement phase."""

    @pytest.mark.asyncio()
    async def test_bead_mapping_passed_to_agent_when_enabled(self, config) -> None:
        """When beads are enabled and mapping exists, it's passed to agent.run()."""
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured_kwargs: list[dict] = []

        async def capturing_agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured_kwargs.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(
            config, [issue], agent_run=capturing_agent
        )

        # Fix enrich_with_comments to return the issue unchanged
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)

        # Wire beads manager
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        phase._beads_manager = mock_beads

        phase._state.set_bead_mapping(42, {"P1": "bd-a1b2", "P2": "bd-c3d4"})

        await phase.run_batch()

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0]["bead_mapping"] == {
            "P1": "bd-a1b2",
            "P2": "bd-c3d4",
        }
        mock_beads.init.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_no_bead_mapping_when_disabled(self, config) -> None:
        """When beads_manager is None, bead_mapping is not passed."""
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured_kwargs: list[dict] = []

        async def capturing_agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured_kwargs.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(
            config, [issue], agent_run=capturing_agent
        )

        await phase.run_batch()

        assert len(captured_kwargs) == 1
        assert "bead_mapping" not in captured_kwargs[0]

    @pytest.mark.asyncio()
    async def test_no_bead_mapping_when_mapping_empty(self, config) -> None:
        """When beads enabled but no mapping exists, bead_mapping is not passed."""
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured_kwargs: list[dict] = []

        async def capturing_agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured_kwargs.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(
            config, [issue], agent_run=capturing_agent
        )
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)

        mock_beads = AsyncMock()
        mock_beads.enabled = True
        phase._beads_manager = mock_beads
        # No mapping set in state

        await phase.run_batch()

        assert len(captured_kwargs) == 1
        assert "bead_mapping" not in captured_kwargs[0]
        mock_beads.init.assert_not_awaited()


# ===========================================================================
# Integration tests — reviewer._build_review_prompt_with_stats with bead_tasks
# ===========================================================================


class TestReviewerBeadPromptIntegration:
    """Tests for per-bead review section in reviewer prompts."""

    def test_bead_tasks_add_per_bead_review_section(self, config, event_bus) -> None:
        """When bead_tasks is provided, the review prompt includes per-bead checks."""
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Add widget", body="Need widgets")
        diff = "diff --git a/src/models.py b/src/models.py\n+class Widget:\n"

        bead_tasks = [
            {
                "id": "bd-a1b2",
                "phase": "P1",
                "status": "closed",
                "files": "src/models.py",
                "tests": "Widget persists",
            },
            {
                "id": "bd-c3d4",
                "phase": "P2",
                "status": "closed",
                "files": "src/api.py",
                "tests": "GET returns list",
            },
        ]

        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=bead_tasks
        )

        assert "## Per-Bead Review" in prompt
        assert "Bead #bd-a1b2" in prompt
        assert "Bead #bd-c3d4" in prompt
        assert "P1" in prompt
        assert "P2" in prompt
        assert "src/models.py" in prompt
        assert "Widget persists" in prompt
        assert "Files listed are present in the diff" in prompt

    def test_no_bead_tasks_no_bead_section(self, config, event_bus) -> None:
        """Without bead_tasks, no per-bead section appears."""
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Fix bug", body="Bug description")
        diff = "diff --git a/src/fix.py b/src/fix.py\n+fixed\n"

        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=None
        )

        assert "## Per-Bead Review" not in prompt

    def test_empty_bead_tasks_no_bead_section(self, config, event_bus) -> None:
        """Empty bead_tasks list produces no per-bead section."""
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Fix bug", body="Bug description")
        diff = "diff --git a/src/fix.py b/src/fix.py\n+fixed\n"

        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=[]
        )

        assert "## Per-Bead Review" not in prompt


# ===========================================================================
# Integration tests — review_phase._build_bead_review_context
# ===========================================================================


class TestReviewPhaseBeadContext:
    """Tests for bead context construction in the review phase."""

    def test_build_bead_context_with_mapping_and_phases(self, config) -> None:
        """Bead context includes file/test info from plan comments."""
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})
        phase._state.set_bead_mapping(42, {"P1": "bd-a1b2", "P2": "bd-c3d4"})

        issue = Task(
            id=42,
            title="Add widget",
            body="Need widgets",
            comments=[_TASK_GRAPH_PLAN],
        )

        result = phase._build_bead_review_context(issue)

        assert result is not None
        assert len(result) == 2

        p1_bead = next(b for b in result if b["phase"] == "P1")
        assert p1_bead["id"] == "bd-a1b2"
        assert "src/models.py" in str(p1_bead["files"])
        assert "Widget persists" in str(p1_bead["tests"])

        p2_bead = next(b for b in result if b["phase"] == "P2")
        assert p2_bead["id"] == "bd-c3d4"
        assert "src/api.py" in str(p2_bead["files"])

    def test_build_bead_context_returns_none_when_disabled(self, config) -> None:
        """Returns None when beads_enabled is False."""
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        issue = Task(id=42, title="Test", body="body")
        assert phase._build_bead_review_context(issue) is None

    def test_build_bead_context_returns_none_when_no_mapping(self, config) -> None:
        """Returns None when no bead mapping exists for the issue."""
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})

        issue = Task(id=999, title="No mapping", body="body")
        assert phase._build_bead_review_context(issue) is None

    def test_build_bead_context_without_plan_comments(self, config) -> None:
        """When issue has no plan comments, bead context uses N/A for files/tests."""
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})
        phase._state.set_bead_mapping(42, {"P1": "bd-a1b2"})

        issue = Task(id=42, title="Test", body="body", comments=[])
        result = phase._build_bead_review_context(issue)

        assert result is not None
        assert len(result) == 1
        assert result[0]["files"] == "N/A"
        assert result[0]["tests"] == "N/A"
