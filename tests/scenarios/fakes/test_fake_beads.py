"""Unit tests for FakeBeads — verifies it faithfully mirrors BeadsManager's API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beads_manager import BeadsManager
from mockworld.fakes.fake_beads import FakeBeads
from task_graph import TaskGraphPhase


@pytest.fixture(params=[BeadsManager, FakeBeads], ids=["real", "fake"])
def contract_manager(request):
    return request.param()


# ---------------------------------------------------------------------------
# ensure_installed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ensure_installed_returns_none() -> None:
    beads = FakeBeads()
    result = await beads.ensure_installed()
    assert result is None


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_is_idempotent(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    await beads.init(cwd=tmp_path)  # calling twice must not raise
    assert beads._initialized is True


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_returns_unique_ids(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    id1 = await beads.create_task(title="alpha", priority="0", cwd=tmp_path)
    id2 = await beads.create_task(title="beta", priority="1", cwd=tmp_path)
    assert id1 != id2


@pytest.mark.asyncio()
async def test_create_task_stores_title_and_priority(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    bead_id = await beads.create_task(title="my task", priority="1", cwd=tmp_path)
    task = await beads.show(bead_id, cwd=tmp_path)
    assert task.title == "my task"
    assert task.priority == 1


# ---------------------------------------------------------------------------
# add_dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_records_edge(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    parent = await beads.create_task(title="parent", priority="0", cwd=tmp_path)
    child = await beads.create_task(title="child", priority="1", cwd=tmp_path)
    await beads.add_dependency(child, parent, cwd=tmp_path)
    shown = await beads.show(child, cwd=tmp_path)
    assert parent in shown.depends_on


@pytest.mark.asyncio()
async def test_add_dependency_unknown_child_raises(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    parent = await beads.create_task(title="p", priority="0", cwd=tmp_path)
    with pytest.raises(KeyError):
        await beads.add_dependency("missing", parent, cwd=tmp_path)


@pytest.mark.asyncio()
async def test_add_dependency_unknown_parent_raises(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    child = await beads.create_task(title="c", priority="1", cwd=tmp_path)
    with pytest.raises(KeyError):
        await beads.add_dependency(child, "missing", cwd=tmp_path)


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_sets_status_in_progress(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    bead_id = await beads.create_task(title="claimable", priority="0", cwd=tmp_path)
    await beads.claim(bead_id, cwd=tmp_path)
    task = await beads.show(bead_id, cwd=tmp_path)
    assert task.status == "in_progress"


@pytest.mark.asyncio()
async def test_claim_rejects_closed_task(tmp_path) -> None:
    beads = FakeBeads()
    bead_id = await beads.create_task(title="closed", priority="0", cwd=tmp_path)
    await beads.close(bead_id, reason="done", cwd=tmp_path)

    with pytest.raises(RuntimeError, match="cannot claim closed"):
        await beads.claim(bead_id, cwd=tmp_path)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_close_sets_status_closed(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    bead_id = await beads.create_task(title="closeable", priority="0", cwd=tmp_path)
    await beads.close(bead_id, reason="done", cwd=tmp_path)
    task = await beads.show(bead_id, cwd=tmp_path)
    assert task.status == "closed"


# ---------------------------------------------------------------------------
# list_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_ready_excludes_tasks_with_open_deps(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    parent = await beads.create_task(title="parent", priority="0", cwd=tmp_path)
    child = await beads.create_task(title="child", priority="1", cwd=tmp_path)
    await beads.add_dependency(child, parent, cwd=tmp_path)

    ready = await beads.list_ready(cwd=tmp_path)
    ready_ids = [t.id for t in ready]
    assert parent in ready_ids
    assert child not in ready_ids


@pytest.mark.asyncio()
async def test_list_ready_includes_task_once_dep_closed(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    parent = await beads.create_task(title="parent", priority="0", cwd=tmp_path)
    child = await beads.create_task(title="child", priority="1", cwd=tmp_path)
    await beads.add_dependency(child, parent, cwd=tmp_path)

    await beads.close(parent, reason="done", cwd=tmp_path)
    ready = await beads.list_ready(cwd=tmp_path)
    ready_ids = [t.id for t in ready]
    assert child in ready_ids


@pytest.mark.asyncio()
async def test_list_ready_excludes_closed_tasks(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    bead_id = await beads.create_task(title="t", priority="0", cwd=tmp_path)
    await beads.close(bead_id, reason="done", cwd=tmp_path)

    ready = await beads.list_ready(cwd=tmp_path)
    assert not any(t.id == bead_id for t in ready)


@pytest.mark.asyncio()
async def test_list_ready_fails_closed_on_dangling_dependency(tmp_path) -> None:
    beads = FakeBeads()
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    issues.write_text(
        '{"id":"child","title":"child","dependencies":[{"depends_on_id":"missing"}]}\n'
    )

    with pytest.raises(RuntimeError, match="unknown dependencies.*missing"):
        await beads.list_ready(cwd=tmp_path)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_show_returns_bead_task_shape(tmp_path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    bead_id = await beads.create_task(title="show me", priority="0", cwd=tmp_path)
    task = await beads.show(bead_id, cwd=tmp_path)
    assert task.id == bead_id
    assert task.title == "show me"
    assert task.priority == 0
    assert task.status == "open"
    assert task.depends_on == []


# ---------------------------------------------------------------------------
# export — writes the per-worktree .beads/issues.jsonl artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_export_writes_issues_jsonl(tmp_path: Path) -> None:
    beads = FakeBeads()
    await beads.init(cwd=tmp_path)
    parent = await beads.create_task(title="alpha", priority="0", cwd=tmp_path)
    child = await beads.create_task(title="beta", priority="1", cwd=tmp_path)
    await beads.add_dependency(child, parent, cwd=tmp_path)

    await beads.export(cwd=tmp_path)

    jsonl = tmp_path / ".beads" / "issues.jsonl"
    assert jsonl.exists()
    lines = [ln for ln in jsonl.read_text().splitlines() if ln.strip()]
    records = [json.loads(line) for line in lines]
    assert {record["title"] for record in records} == {"alpha", "beta"}
    child_record = next(record for record in records if record["id"] == child)
    assert child_record["dependencies"][0]["depends_on_id"] == parent


@pytest.mark.asyncio()
async def test_contract_recovers_stable_phase_identity_and_persists_lifecycle(
    contract_manager, tmp_path
) -> None:
    phases = [
        TaskGraphPhase(id="P1", name="root", files=[], tests=[], depends_on=[]),
        TaskGraphPhase(id="P2", name="child", files=[], tests=[], depends_on=["P1"]),
    ]

    first = await contract_manager.create_from_phases(phases, 42, tmp_path)
    second = await contract_manager.create_from_phases(phases, 42, tmp_path)
    await contract_manager.claim(first["P1"], tmp_path)
    await contract_manager.close(first["P1"], "root complete", tmp_path)

    records = [
        json.loads(line)
        for line in (tmp_path / ".beads" / "issues.jsonl").read_text().splitlines()
    ]
    assert first == second
    assert len(records) == 2
    assert {record["external_ref"] for record in records} == {
        "hydraflow-factory:issue:42:phase:P1",
        "hydraflow-factory:issue:42:phase:P2",
    }
    root = next(record for record in records if record["id"] == first["P1"])
    assert root["status"] == "closed"
    assert root["close_reason"] == "root complete"


@pytest.mark.asyncio()
async def test_contract_dependency_mutations_are_idempotent_and_cycle_safe(
    contract_manager, tmp_path
) -> None:
    parent = await contract_manager.create_task("parent", "0", tmp_path)
    child = await contract_manager.create_task("child", "1", tmp_path)
    await contract_manager.add_dependency(child, parent, tmp_path)
    await contract_manager.add_dependency(child, parent, tmp_path)
    issues = tmp_path / ".beads" / "issues.jsonl"
    original = issues.read_bytes()

    with pytest.raises(RuntimeError, match="dependency cycle"):
        await contract_manager.add_dependency(parent, child, tmp_path)

    assert issues.read_bytes() == original
    assert (await contract_manager.show(child, tmp_path)).depends_on == [parent]


@pytest.mark.asyncio()
async def test_contract_closed_task_cannot_be_reclaimed(
    contract_manager, tmp_path
) -> None:
    task = await contract_manager.create_task("task", "0", tmp_path)
    await contract_manager.close(task, "done", tmp_path)

    with pytest.raises(RuntimeError, match="cannot claim closed"):
        await contract_manager.claim(task, tmp_path)
