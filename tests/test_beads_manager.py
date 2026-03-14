"""Tests for the BeadsManager — bd CLI wrapper."""

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


# --- No-op when disabled ---


@pytest.mark.asyncio()
async def test_disabled_is_available(disabled_manager):
    assert await disabled_manager.is_available() is False


@pytest.mark.asyncio()
async def test_disabled_init(disabled_manager):
    assert await disabled_manager.init(Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_create_task(disabled_manager):
    assert await disabled_manager.create_task("title", "high", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_add_dependency(disabled_manager):
    assert await disabled_manager.add_dependency("1", "2", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_claim(disabled_manager):
    assert await disabled_manager.claim("1", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_close(disabled_manager):
    assert await disabled_manager.close("1", "done", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_list_ready(disabled_manager):
    assert await disabled_manager.list_ready(Path("/tmp")) == []


@pytest.mark.asyncio()
async def test_disabled_show(disabled_manager):
    assert await disabled_manager.show("1", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_create_from_phases(disabled_manager):
    phases = [
        TaskGraphPhase(id="P1", name="P1 — Setup", files=[], tests=[], depends_on=[])
    ]
    assert await disabled_manager.create_from_phases(phases, 42, Path("/tmp")) == {}


# --- is_available ---


@pytest.mark.asyncio()
async def test_is_available_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "bd version 0.1.0"
        assert await manager.is_available() is True
        mock_run.assert_called_once_with("bd", "version", timeout=10.0)


@pytest.mark.asyncio()
async def test_is_available_not_installed(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("bd not found")
        assert await manager.is_available() is False


# --- init ---


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


# --- create_task ---


@pytest.mark.asyncio()
async def test_create_task_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Created task #42"
        result = await manager.create_task("My task", "high", Path("/repo"))
        assert result == "42"


@pytest.mark.asyncio()
async def test_create_task_no_id_in_output(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Something unexpected"
        result = await manager.create_task("My task", "high", Path("/repo"))
        assert result is None


@pytest.mark.asyncio()
async def test_create_task_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        result = await manager.create_task("My task", "high", Path("/repo"))
        assert result is None


# --- add_dependency ---


@pytest.mark.asyncio()
async def test_add_dependency_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Dependency added"
        assert await manager.add_dependency("2", "1", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd", "dep", "add", "2", "1", cwd=Path("/repo"), timeout=30.0
        )


# --- claim ---


@pytest.mark.asyncio()
async def test_claim_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Claimed"
        assert await manager.claim("42", Path("/repo")) is True


# --- close ---


@pytest.mark.asyncio()
async def test_close_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Closed"
        assert await manager.close("42", "done", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd", "close", "42", "--reason", "done", cwd=Path("/repo"), timeout=30.0
        )


# --- list_ready ---


@pytest.mark.asyncio()
async def test_list_ready_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "#1 My task [open] [high]\n#2 Another [open] [medium]\n"
        result = await manager.list_ready(Path("/repo"))
        assert len(result) == 2
        assert result[0].id == "1"
        assert result[0].title == "My task"
        assert result[0].status == "open"
        assert result[0].priority == "high"


# --- show ---


@pytest.mark.asyncio()
async def test_show_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (
            "Title: My task\nStatus: in_progress\nPriority: high\nDepends on: #1, #3\n"
        )
        result = await manager.show("42", Path("/repo"))
        assert result is not None
        assert result.id == "42"
        assert result.title == "My task"
        assert result.status == "in_progress"
        assert result.priority == "high"
        assert result.depends_on == ["1", "3"]


# --- create_from_phases ---


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

    async def mock_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        cmd_args = list(args)
        if "add" in cmd_args:
            # Return different IDs for each create
            return f"Created task #{100 + call_count}"
        if "dep" in cmd_args:
            return "Dependency added"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert "P1" in mapping
    assert "P2" in mapping
    # Verify both phases got bead IDs
    assert len(mapping) == 2


@pytest.mark.asyncio()
async def test_create_from_phases_partial_failure(manager):
    """Test that partial failures during bead creation are handled gracefully."""
    phases = [
        TaskGraphPhase(
            id="P1",
            name="P1 — Model",
            files=[],
            tests=[],
            depends_on=[],
        ),
        TaskGraphPhase(
            id="P2",
            name="P2 — API",
            files=[],
            tests=[],
            depends_on=["P1"],
        ),
    ]

    async def mock_run(*args, **kwargs):
        cmd_args = list(args)
        if "add" in cmd_args and "P2" in str(cmd_args):
            raise RuntimeError("failed")
        if "add" in cmd_args:
            return "Created task #10"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    # P1 should succeed, P2 should be missing
    assert "P1" in mapping


# --- _parse_task_list ---


def test_parse_task_list_empty():
    assert BeadsManager._parse_task_list("") == []


def test_parse_task_list_multiple():
    output = "#1 Task A [open] [high]\n#2 Task B [closed] [low]\n"
    tasks = BeadsManager._parse_task_list(output)
    assert len(tasks) == 2
    assert tasks[0] == BeadTask(id="1", title="Task A", status="open", priority="high")
    assert tasks[1] == BeadTask(id="2", title="Task B", status="closed", priority="low")


# --- _parse_show_output ---


def test_parse_show_output():
    output = "Title: Test task\nStatus: open\nPriority: medium\nDepends on: #5\n"
    task = BeadsManager._parse_show_output("99", output)
    assert task.id == "99"
    assert task.title == "Test task"
    assert task.depends_on == ["5"]


def test_parse_show_output_minimal():
    task = BeadsManager._parse_show_output("1", "")
    assert task.id == "1"
    assert task.title == "Bead #1"


# --- State roundtrip ---


def test_bead_mapping_state_roundtrip(tmp_path):
    """Verify bead mappings survive a state save/load cycle."""
    from state import StateTracker

    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)

    mapping = {"P1": "10", "P2": "20", "P3": "30"}
    tracker.set_bead_mapping(42, mapping)

    assert tracker.get_bead_mapping(42) == mapping
    assert tracker.get_bead_mapping(999) == {}

    # Reload from disk
    tracker2 = StateTracker(state_file)
    assert tracker2.get_bead_mapping(42) == mapping
