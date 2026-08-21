"""Tests for the per-worktree JSONL BeadsManager and integration points."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import re
import stat
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from beads_manager import BeadsManager, BeadsNotInstalledError, BeadTask
from task_graph import TaskGraphPhase


@pytest.fixture()
def manager():
    return BeadsManager()


def _paused_jsonl_writer(worktree, started, release, results) -> None:
    """Process helper: pause after the locked read and report create outcome."""
    original_read = BeadsManager._read_validated_records.__func__

    def pause_after_read(cls, handle):
        records = original_read(cls, handle)
        started.set()
        if not release.wait(timeout=10):
            raise TimeoutError("test did not release paused JSONL writer")
        return records

    BeadsManager._read_validated_records = classmethod(  # type: ignore[method-assign]
        pause_after_read
    )
    try:
        task_id = asyncio.run(BeadsManager().create_task("first", "1", Path(worktree)))
    except Exception as exc:  # noqa: BLE001 - child reports exact boundary failure
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", task_id))


def _jsonl_writer(worktree, started, done, results) -> None:
    """Process helper: create a task and expose entry/completion events."""
    started.set()
    try:
        task_id = asyncio.run(BeadsManager().create_task("second", "1", Path(worktree)))
    except Exception as exc:  # noqa: BLE001 - child reports exact boundary failure
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", task_id))
    finally:
        done.set()


# ---------------------------------------------------------------------------
# JSONL bootstrap — no external executable or database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ensure_installed_has_no_executable_dependency(manager):
    await manager.ensure_installed()


def test_legacy_not_installed_exception_remains_importable():
    assert issubclass(BeadsNotInstalledError, RuntimeError)


def test_manager_source_has_no_bd_or_dolt_subprocess_path():
    source = Path(BeadsManager.__module__.replace(".", "/"))
    source = Path(__file__).parents[1] / "src" / f"{source.name}.py"
    text = source.read_text()
    assert "run_subprocess" not in text
    assert '"bd"' not in text
    assert '"dolt"' not in text


def test_repo_runtime_has_no_database_backed_task_cli_path():
    repo = Path(__file__).parents[1]
    runtime_files: set[Path] = {
        path
        for root in (
            repo / "src",
            repo / "scripts",
            repo / ".github",
            repo / ".githooks",
            repo / ".claude",
        )
        for path in root.rglob("*")
        if path.is_file()
    }
    runtime_files.update(
        path
        for path in (repo / "tests").rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sh", ".json", ".toml", ".txt", ".yaml", ".yml"}
        and "fixtures" not in path.parts
        and path.resolve() != Path(__file__).resolve()
    )
    root_operational_files = {
        "AGENTS.md",
        "CLAUDE.md",
        "Makefile",
        ".dockerignore",
        ".env.sample",
        ".gitignore",
        ".lgtm.yml",
        "claude.sh",
        "docker-compose.sandbox.yml",
        "pyproject.toml",
    }
    runtime_files.update(
        path
        for path in repo.iterdir()
        if path.is_file()
        and (path.name in root_operational_files or path.name.startswith("Dockerfile"))
    )
    runtime_files.update(
        path for path in (repo / ".beads").rglob("*") if path.is_file()
    )
    runtime_files.update(
        path
        for root in (repo / "docs" / "adr", repo / "docs" / "standards")
        for path in root.rglob("*.md")
        if path.is_file()
    )

    tracked_locator = repo / ".beads" / "metadata.json"
    assert not tracked_locator.exists(), (
        ".beads/metadata.json must not ship a server/database locator into worktrees"
    )

    # These exact fragments are the only database-client references permitted
    # in operational files: they remove a stale client inherited from an older
    # base image and make both the image CI and runtime smoke test fail if one
    # is present. Mask them before the general execution-path scan below.
    absence_guards = {
        repo / "Dockerfile.agent": (
            "RUN rm -f /usr/bin/bd /usr/local/bin/bd \\\n"
            "    && rm -rf /usr/lib/node_modules/@beads/bd "
            "/usr/local/lib/node_modules/@beads/bd",
        ),
        repo / "scripts" / "docker-smoke-test.sh": (
            'check_absent "database task CLI absent" command -v bd',
            'check_absent "database task npm module absent" test -e '
            "/usr/lib/node_modules/@beads/bd",
            'check_absent "local-prefix database task npm module absent" test -e '
            "/usr/local/lib/node_modules/@beads/bd",
        ),
        repo / ".github" / "workflows" / "build-agent-base-image.yml": (
            "if command -v bd >/dev/null 2>&1; then",
            "test ! -e /usr/lib/node_modules/@beads/bd",
            "test ! -e /usr/local/lib/node_modules/@beads/bd",
        ),
    }
    forbidden = re.compile(
        r"@beads/bd|/usr/bin/bd|\bcommand\s+-v\s+bd\b|"
        r"(?:^|[;&|`()\s])bd\s+(?:--version|create|update|close|ready|show|"
        r"init|export|dolt|hooks|link|note|list|config|doctor|migrate|bootstrap|"
        r"sync|push|pull|claim)\b|"
        r"[\"']bd[\"']\s*,\s*[\"'](?:create|update|close|ready|show|init|"
        r"export|dolt|hooks|link|note|list|config|doctor|migrate|bootstrap|sync|"
        r"push|pull|claim)[\"']|"
        r"\bbeads\s+(?:create|update|close|ready|show|note|list)\b|"
        r"\bdolt\s+(?:push|pull|sql|status|server|migrate|clone)\b|"
        r"\b(?:track(?:ed|ing)?|file(?:d)?|record(?:ed)?)\b[^\n]{0,80}"
        r"\b(?:in|with|via)\s+[`'\"]?bd\b|"
        r"__bd_hook__|script_run_with_beads|BD_CWD|file deferred work in bd",
        re.IGNORECASE | re.MULTILINE,
    )
    offenders: list[str] = []
    for path in runtime_files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for guard in absence_guards.get(path, ()):
            assert guard in text, f"missing task-store isolation guard in {path}"
            text = text.replace(guard, "")
        if forbidden.search(text):
            offenders.append(str(path.relative_to(repo)))

    assert sorted(offenders) == []


def test_base_image_absence_probes_are_fail_fast():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "build-agent-base-image.yml"
    ).read_text(encoding="utf-8")
    invocation = re.search(
        r"docker run[^\n]*\sbash\s+-(?P<flags>[a-z]+)\s+'"
        r"(?P<body>.*?)\n\s+'",
        workflow,
        re.DOTALL,
    )
    assert invocation is not None

    # `-e` is what makes a failed bare absence probe terminate the inner shell
    # before its final success echo can mask the failure; `-c` executes the
    # captured body. Parse the option set so ordering or combined flags may
    # change without weakening either semantic.
    assert {"c", "e"} <= set(invocation.group("flags"))
    body = invocation.group("body")
    probes = (
        "test ! -e /usr/lib/node_modules/@beads/bd",
        "test ! -e /usr/local/lib/node_modules/@beads/bd",
    )
    for probe in probes:
        assert probe in body
        assert body.index(probe) < body.index('echo "=== All tools present ==="')


# ---------------------------------------------------------------------------
# init/export — JSONL is canonical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_repairs_permissions_and_creates_jsonl(manager, tmp_path):
    beads_dir = tmp_path / ".beads"
    beads_dir.mkdir(mode=0o755)

    await manager.init(tmp_path)

    issues = beads_dir / "issues.jsonl"
    assert issues.read_bytes() == b""
    assert stat.S_IMODE(beads_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(issues.stat().st_mode) == 0o600
    assert stat.S_IMODE((beads_dir / ".issues.jsonl.lock").stat().st_mode) == 0o600


@pytest.mark.asyncio()
async def test_init_rejects_symlinked_beads_directory_without_touching_target(
    manager, tmp_path
):
    external = tmp_path / "external-beads"
    external.mkdir()
    external.chmod(0o750)
    external_issues = external / "issues.jsonl"
    original = b'{"id":"external","title":"do not touch"}\n'
    external_issues.write_bytes(original)
    external_issues.chmod(0o640)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".beads").symlink_to(external, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unsafe Beads path is a symlink"):
        await manager.init(worktree)

    assert (worktree / ".beads").is_symlink()
    assert external_issues.read_bytes() == original
    assert stat.S_IMODE(external.stat().st_mode) == 0o750
    assert stat.S_IMODE(external_issues.stat().st_mode) == 0o640


@pytest.mark.asyncio()
async def test_init_rejects_symlinked_issues_file_without_touching_target(
    manager, tmp_path
):
    external = tmp_path / "external-issues.jsonl"
    original = b'{"id":"external","title":"do not touch"}\n'
    external.write_bytes(original)
    external.chmod(0o640)
    beads_dir = tmp_path / "worktree" / ".beads"
    beads_dir.mkdir(parents=True)
    issues = beads_dir / "issues.jsonl"
    issues.symlink_to(external)

    with pytest.raises(RuntimeError, match="unsafe Beads path is a symlink"):
        await manager.init(tmp_path / "worktree")

    assert issues.is_symlink()
    assert external.read_bytes() == original
    assert stat.S_IMODE(external.stat().st_mode) == 0o640


@pytest.mark.asyncio()
async def test_init_detects_issues_path_swap_without_touching_external_target(
    manager, tmp_path, monkeypatch
):
    external = tmp_path / "external-issues.jsonl"
    original = b'{"id":"external","title":"do not touch"}\n'
    external.write_bytes(original)
    external.chmod(0o640)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    issues = worktree / ".beads" / "issues.jsonl"
    original_open = BeadsManager._open_regular_file
    swapped = False

    def open_then_swap(directory_fd, name, display_path, *, create):
        nonlocal swapped
        fd = original_open(
            directory_fd,
            name,
            display_path,
            create=create,
        )
        if name == "issues.jsonl" and not swapped:
            swapped = True
            issues.rename(issues.with_name("issues.local"))
            issues.symlink_to(external)
        return fd

    monkeypatch.setattr(
        BeadsManager,
        "_open_regular_file",
        staticmethod(open_then_swap),
    )

    with pytest.raises(RuntimeError, match="unsafe Beads path changed"):
        await manager.init(worktree)

    assert external.read_bytes() == original
    assert stat.S_IMODE(external.stat().st_mode) == 0o640


@pytest.mark.asyncio()
async def test_init_rejects_symlinked_lock_file_without_touching_target(
    manager, tmp_path
):
    external = tmp_path / "external.lock"
    original = b"external lock contents"
    external.write_bytes(original)
    external.chmod(0o640)
    beads_dir = tmp_path / "worktree" / ".beads"
    beads_dir.mkdir(parents=True)
    lock = beads_dir / ".issues.jsonl.lock"
    lock.symlink_to(external)

    with pytest.raises(RuntimeError, match="unsafe Beads path is a symlink"):
        await manager.init(tmp_path / "worktree")

    assert lock.is_symlink()
    assert external.read_bytes() == original
    assert stat.S_IMODE(external.stat().st_mode) == 0o640


@pytest.mark.asyncio()
async def test_init_preserves_valid_jsonl_bytes(manager, tmp_path):
    beads_dir = tmp_path / ".beads"
    beads_dir.mkdir(mode=0o755)
    issues = beads_dir / "issues.jsonl"
    original = b'  {"_type": "issue", "id": "x", "title": "t"}\n\n'
    issues.write_bytes(original)
    issues.chmod(0o644)

    await manager.init(tmp_path)

    assert issues.read_bytes() == original
    assert stat.S_IMODE(beads_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(issues.stat().st_mode) == 0o600


@pytest.mark.asyncio()
async def test_init_rejects_invalid_jsonl_without_overwrite(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"id":"valid","title":"valid"}\nnot-json\n'
    issues.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"issues\.jsonl:2"):
        await manager.init(tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_init_rejects_duplicate_task_ids_without_overwrite(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"id":"same","title":"first"}\n{"id":"same","title":"second"}\n'
    issues.write_bytes(original)

    with pytest.raises(RuntimeError, match="duplicate Beads task ID"):
        await manager.init(tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"title": "missing ID"}, "task ID"),
        ({"id": 42, "title": "numeric ID"}, "task ID"),
        ({"id": " ", "title": "blank ID"}, "task ID"),
        ({"id": "x"}, "title"),
        ({"id": "x", "title": 42}, "title"),
        ({"id": "x", "title": "task", "status": "bogus"}, "status"),
        ({"id": "x", "title": "task", "priority": "1"}, "priority"),
        ({"id": "x", "title": "task", "priority": True}, "priority"),
        ({"id": "x", "title": "task", "priority": 5}, "priority"),
    ],
)
async def test_init_rejects_malformed_issue_core_fields_without_overwrite(
    manager, tmp_path, record, message
):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = (json.dumps(record) + "\n").encode()
    issues.write_bytes(original)

    with pytest.raises(RuntimeError, match=message):
        await manager.init(tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_store_operations_reject_dangling_dependency_without_overwrite(
    manager, tmp_path
):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = (
        b'{"id":"child","title":"child","status":"open",'
        b'"dependencies":[{"depends_on_id":"missing"}]}\n'
    )
    issues.write_bytes(original)

    for operation in (
        lambda: manager.init(tmp_path),
        lambda: manager.export(tmp_path),
        lambda: manager.list_ready(tmp_path),
        lambda: manager.create_task("new", "1", tmp_path),
    ):
        with pytest.raises(RuntimeError, match="unknown dependencies.*missing"):
            await operation()
        assert issues.read_bytes() == original


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "records",
    [
        [
            {
                "id": "self",
                "title": "self",
                "dependencies": [{"depends_on_id": "self"}],
            }
        ],
        [
            {
                "id": "first",
                "title": "first",
                "dependencies": [{"depends_on_id": "second"}],
            },
            {
                "id": "second",
                "title": "second",
                "dependencies": [{"depends_on_id": "first"}],
            },
        ],
    ],
)
async def test_store_operations_reject_dependency_cycles_without_overwrite(
    manager, tmp_path, records
):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = "".join(json.dumps(record) + "\n" for record in records).encode()
    issues.write_bytes(original)
    target = records[0]["id"]

    for operation in (
        lambda: manager.init(tmp_path),
        lambda: manager.export(tmp_path),
        lambda: manager.show(target, tmp_path),
        lambda: manager.list_ready(tmp_path),
        lambda: manager.create_task("new", "1", tmp_path),
        lambda: manager.claim(target, tmp_path),
        lambda: manager.close(target, "done", tmp_path),
    ):
        with pytest.raises(RuntimeError, match="self-dependency|dependency cycle"):
            await operation()
        assert issues.read_bytes() == original


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "dependencies",
    [
        {"depends_on_id": "parent"},
        [{"type": "blocks"}],
        [42],
        [""],
    ],
)
async def test_store_rejects_malformed_dependencies_without_overwrite(
    manager, tmp_path, dependencies
):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = (
        json.dumps(
            {
                "id": "child",
                "title": "child",
                "status": "open",
                "dependencies": dependencies,
            }
        ).encode()
        + b"\n"
    )
    issues.write_bytes(original)

    for operation in (manager.init, manager.export, manager.list_ready):
        with pytest.raises(RuntimeError, match="invalid dependenc"):
            await operation(tmp_path)
        assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_export_validates_without_rewriting(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"id": "x", "title": "spaced"}\n'
    issues.write_bytes(original)

    await manager.export(tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_export_rejects_invalid_jsonl_without_overwrite(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"id":"valid","title":"valid"}\n["not", "an", "object"]\n'
    issues.write_bytes(original)

    with pytest.raises(RuntimeError, match=r"issues\.jsonl:2"):
        await manager.export(tmp_path)

    assert issues.read_bytes() == original


# ---------------------------------------------------------------------------
# create_task — direct atomic JSONL mutation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_persists_canonical_record(manager, tmp_path):
    bead_id = await manager.create_task("My task", "0", tmp_path)

    record = json.loads((tmp_path / ".beads" / "issues.jsonl").read_text())
    expected_prefix = re.sub(r"[^a-z0-9]+", "-", tmp_path.name.lower()).strip("-")
    assert bead_id.startswith(f"{expected_prefix[:24].rstrip('-')}-")
    assert re.fullmatch(r"[a-z0-9-]+-[0-9a-f]{8}", bead_id)
    assert record == {
        "_type": "issue",
        "id": bead_id,
        "title": "My task",
        "status": "open",
        "priority": 0,
        "dependencies": [],
    }


@pytest.mark.asyncio()
@pytest.mark.parametrize("priority", ["-1", "5", "high"])
async def test_create_task_rejects_invalid_priority(manager, tmp_path, priority):
    with pytest.raises(ValueError, match="invalid Beads priority"):
        await manager.create_task("My task", priority, tmp_path)


@pytest.mark.asyncio()
async def test_create_task_rejects_blank_title_before_initializing(manager, tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        await manager.create_task(" ", "1", tmp_path)

    assert not (tmp_path / ".beads").exists()


@pytest.mark.asyncio()
async def test_create_task_uses_atomic_same_directory_replace(manager, tmp_path):
    await manager.init(tmp_path)
    with patch("beads_manager.os.replace", wraps=os.replace) as replace:
        await manager.create_task("My task", "2", tmp_path)

    replace.assert_called_once()
    assert replace.call_args.args[1] == "issues.jsonl"
    assert (
        replace.call_args.kwargs["src_dir_fd"] == replace.call_args.kwargs["dst_dir_fd"]
    )
    assert '"title":"My task"' in (tmp_path / ".beads" / "issues.jsonl").read_text()


@pytest.mark.asyncio()
async def test_create_task_short_write_preserves_existing_store(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"_type":"memory","key":"preserved"}\n'
    issues.write_bytes(original)

    with (
        patch("beads_manager.os.write", return_value=0),
        pytest.raises(OSError, match="short write"),
    ):
        await manager.create_task("My task", "2", tmp_path)

    assert issues.read_bytes() == original
    assert list(issues.parent.glob(".issues.jsonl-*.tmp")) == []


@pytest.mark.asyncio()
async def test_concurrent_creates_are_serialized_without_lost_rows(manager, tmp_path):
    ids = await asyncio.gather(
        *(manager.create_task(f"task {index}", "2", tmp_path) for index in range(20))
    )

    records = [
        json.loads(line)
        for line in (tmp_path / ".beads" / "issues.jsonl").read_text().splitlines()
    ]
    assert len(ids) == len(set(ids)) == 20
    assert {record["id"] for record in records} == set(ids)


@pytest.mark.asyncio()
async def test_replaced_named_lock_cannot_admit_a_concurrent_writer(
    manager, tmp_path, monkeypatch
):
    await manager.init(tmp_path)
    lock_path = tmp_path / ".beads" / ".issues.jsonl.lock"
    first_has_lock = threading.Event()
    release_first = threading.Event()
    select_first = threading.Lock()
    should_pause = True
    original_read = BeadsManager._read_validated_records.__func__

    def pause_first_reader(cls, handle):
        nonlocal should_pause
        records = original_read(cls, handle)
        with select_first:
            pause = should_pause
            should_pause = False
        if pause:
            first_has_lock.set()
            if not release_first.wait(timeout=5):
                raise TimeoutError("test did not release first JSONL writer")
        return records

    monkeypatch.setattr(
        BeadsManager,
        "_read_validated_records",
        classmethod(pause_first_reader),
    )
    first = asyncio.create_task(manager.create_task("first", "1", tmp_path))
    assert await asyncio.to_thread(first_has_lock.wait, 2)

    held_inode = lock_path.with_name("held-lock-inode")
    lock_path.rename(held_inode)
    lock_path.write_bytes(b"replacement lock inode")
    second = asyncio.create_task(manager.create_task("second", "1", tmp_path))
    await asyncio.sleep(0.05)
    assert not second.done()

    release_first.set()
    with pytest.raises(RuntimeError, match="unsafe Beads path changed"):
        await first
    second_id = await asyncio.wait_for(second, timeout=2)

    records = [
        json.loads(line)
        for line in (tmp_path / ".beads" / "issues.jsonl").read_text().splitlines()
    ]
    assert [record["id"] for record in records] == [second_id]
    assert [record["title"] for record in records] == ["second"]


def test_replaced_named_lock_cannot_bypass_serialization_across_processes(
    manager, tmp_path
):
    asyncio.run(manager.init(tmp_path))
    lock_path = tmp_path / ".beads" / ".issues.jsonl.lock"
    process_context = multiprocessing.get_context("spawn")
    first_started = process_context.Event()
    release_first = process_context.Event()
    second_started = process_context.Event()
    second_done = process_context.Event()
    results = process_context.Queue()
    first = process_context.Process(
        target=_paused_jsonl_writer,
        args=(str(tmp_path), first_started, release_first, results),
    )
    second = process_context.Process(
        target=_jsonl_writer,
        args=(str(tmp_path), second_started, second_done, results),
    )
    started_processes = []

    try:
        first.start()
        started_processes.append(first)
        assert first_started.wait(timeout=5)
        lock_path.rename(lock_path.with_name("held-lock-inode"))
        lock_path.write_bytes(b"replacement lock inode")
        second.start()
        started_processes.append(second)
        assert second_started.wait(timeout=5)
        assert not second_done.wait(timeout=0.2)

        release_first.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert first.exitcode == 0
        assert second.exitcode == 0
    finally:
        release_first.set()
        for process in started_processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)

    outcomes = [results.get(timeout=2), results.get(timeout=2)]
    assert any(
        outcome[0] == "error" and "unsafe Beads path changed" in outcome[2]
        for outcome in outcomes
    )
    successful = next(outcome for outcome in outcomes if outcome[0] == "ok")
    records = [
        json.loads(line)
        for line in (tmp_path / ".beads" / "issues.jsonl").read_text().splitlines()
    ]
    assert [record["id"] for record in records] == [successful[1]]
    assert [record["title"] for record in records] == ["second"]


# ---------------------------------------------------------------------------
# add_dependency — JSONL dependency graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_controls_readiness(manager, tmp_path):
    parent = await manager.create_task("parent", "0", tmp_path)
    child = await manager.create_task("child", "1", tmp_path)

    await manager.add_dependency(child, parent, tmp_path)

    assert [task.id for task in await manager.list_ready(tmp_path)] == [parent]
    await manager.close(parent, "done", tmp_path)
    assert [task.id for task in await manager.list_ready(tmp_path)] == [child]
    assert (await manager.show(child, tmp_path)).depends_on == [parent]


@pytest.mark.asyncio()
async def test_add_dependency_is_idempotent(manager, tmp_path):
    parent = await manager.create_task("parent", "0", tmp_path)
    child = await manager.create_task("child", "1", tmp_path)

    await manager.add_dependency(child, parent, tmp_path)
    await manager.add_dependency(child, parent, tmp_path)

    assert (await manager.show(child, tmp_path)).depends_on == [parent]


@pytest.mark.asyncio()
async def test_add_dependency_preserves_legacy_depends_on_field(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    issues.write_text(
        '{"id":"parent","title":"parent","status":"open"}\n'
        '{"id":"existing","title":"existing","status":"closed"}\n'
        '{"id":"child","title":"child","status":"open",'
        '"depends_on":["existing"]}\n'
    )

    await manager.add_dependency("child", "parent", tmp_path)

    records = [json.loads(line) for line in issues.read_text().splitlines()]
    child = next(record for record in records if record.get("id") == "child")
    assert child["depends_on"] == ["existing", "parent"]
    assert "dependencies" not in child


@pytest.mark.asyncio()
async def test_add_dependency_rejects_unknown_tasks(manager, tmp_path):
    known = await manager.create_task("known", "0", tmp_path)
    with pytest.raises(KeyError, match="missing"):
        await manager.add_dependency("missing", known, tmp_path)
    with pytest.raises(KeyError, match="missing"):
        await manager.add_dependency(known, "missing", tmp_path)


@pytest.mark.asyncio()
async def test_add_dependency_rejects_self_dependency_without_overwrite(
    manager, tmp_path
):
    task = await manager.create_task("task", "0", tmp_path)
    issues = tmp_path / ".beads" / "issues.jsonl"
    original = issues.read_bytes()

    with pytest.raises(RuntimeError, match="self-dependency"):
        await manager.add_dependency(task, task, tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_add_dependency_rejects_cycle_without_overwrite(manager, tmp_path):
    parent = await manager.create_task("parent", "0", tmp_path)
    child = await manager.create_task("child", "1", tmp_path)
    await manager.add_dependency(child, parent, tmp_path)
    issues = tmp_path / ".beads" / "issues.jsonl"
    original = issues.read_bytes()

    with pytest.raises(RuntimeError, match="dependency cycle"):
        await manager.add_dependency(parent, child, tmp_path)

    assert issues.read_bytes() == original


# ---------------------------------------------------------------------------
# lifecycle and reads — direct JSONL operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_and_close_persist_lifecycle(manager, tmp_path):
    bead_id = await manager.create_task("phase", "0", tmp_path)

    await manager.claim(bead_id, tmp_path)
    claimed = await manager.show(bead_id, tmp_path)
    assert claimed.status == "in_progress"

    await manager.close(bead_id, "Phase complete", tmp_path)
    closed = await manager.show(bead_id, tmp_path)
    record = json.loads((tmp_path / ".beads" / "issues.jsonl").read_text())
    assert closed.status == "closed"
    assert record["close_reason"] == "Phase complete"


@pytest.mark.asyncio()
async def test_claim_rejects_closed_task_without_reopening(manager, tmp_path):
    bead_id = await manager.create_task("phase", "0", tmp_path)
    await manager.close(bead_id, "done", tmp_path)

    with pytest.raises(RuntimeError, match="cannot claim closed"):
        await manager.claim(bead_id, tmp_path)

    assert (await manager.show(bead_id, tmp_path)).status == "closed"


@pytest.mark.asyncio()
async def test_agent_commit_pending_persists_finalized_jsonl(
    manager, config, event_bus, tmp_path
):
    import subprocess

    from agent import AgentRunner
    from tests.conftest import TaskFactory
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    repo = tmp_path / "worktree"
    init_test_worktree(repo)
    bead_id = await manager.create_task("phase", "0", repo)
    await manager.claim(bead_id, repo)
    subprocess.run(
        ["git", "add", ".beads/issues.jsonl"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "record active phase"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    await manager.close(bead_id, "Phase complete", repo)

    persisted = await AgentRunner(config, event_bus).commit_pending(
        TaskFactory.create(id=42, title="finish phase"), repo
    )

    committed = subprocess.run(
        ["git", "show", "HEAD:.beads/issues.jsonl"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert persisted is True
    assert json.loads(committed)["status"] == "closed"
    assert (
        subprocess.run(
            ["git", "status", "--porcelain", "--", ".beads/issues.jsonl"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )


@pytest.mark.asyncio()
async def test_lifecycle_operations_reject_unknown_task(manager, tmp_path):
    with pytest.raises(KeyError, match="missing"):
        await manager.claim("missing", tmp_path)
    with pytest.raises(KeyError, match="missing"):
        await manager.close("missing", "done", tmp_path)
    with pytest.raises(KeyError, match="missing"):
        await manager.show("missing", tmp_path)


@pytest.mark.asyncio()
async def test_mutation_preserves_unknown_records_and_issue_fields(manager, tmp_path):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    issues.write_text(
        '{"_type":"memory","key":"keep-me"}\n'
        '{"_type":"issue","id":"repo-4yu","title":"phase",'
        '"status":"open","priority":1,"custom":{"nested":true}}\n'
    )

    await manager.claim("repo-4yu", tmp_path)

    records = [json.loads(line) for line in issues.read_text().splitlines()]
    assert records[0] == {"_type": "memory", "key": "keep-me"}
    assert records[1]["status"] == "in_progress"
    assert records[1]["custom"] == {"nested": True}


@pytest.mark.asyncio()
async def test_list_ready_initializes_empty_store(manager, tmp_path):
    assert await manager.list_ready(tmp_path) == []
    assert (tmp_path / ".beads" / "issues.jsonl").read_bytes() == b""


@pytest.mark.asyncio()
async def test_list_ready_includes_claimed_unblocked_tasks(manager, tmp_path):
    bead_id = await manager.create_task("phase", "0", tmp_path)
    await manager.claim(bead_id, tmp_path)

    ready = await manager.list_ready(tmp_path)

    assert [task.id for task in ready] == [bead_id]
    assert ready[0].status == "in_progress"


# ---------------------------------------------------------------------------
# create_from_phases — one atomic task-graph transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_from_phases_persists_graph(manager, tmp_path):
    phases = [
        TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/model.py"],
            tests=["test model"],
            depends_on=[],
        ),
        TaskGraphPhase(
            id="P2",
            name="P2 — API",
            files=["src/api.py"],
            tests=["test api"],
            depends_on=["P1"],
        ),
    ]

    mapping = await manager.create_from_phases(phases, 42, tmp_path)

    assert mapping.keys() == {"P1", "P2"}
    assert mapping["P1"] != mapping["P2"]
    p1 = await manager.show(mapping["P1"], tmp_path)
    p2 = await manager.show(mapping["P2"], tmp_path)
    assert p1.title == "Issue #42 — P1 — Data Model"
    assert p1.priority == 0
    assert p1.depends_on == []
    assert p2.priority == 1
    assert p2.depends_on == [mapping["P1"]]
    assert [task.id for task in await manager.list_ready(tmp_path)] == [mapping["P1"]]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("missing", "incomplete factory phase graph"),
        ("duplicate", "duplicate factory phase identity"),
        ("dependencies", "dependencies do not match"),
    ],
)
async def test_create_from_phases_rejects_corrupt_stable_graph_without_append(
    manager, tmp_path, corruption, message
):
    phases = [
        TaskGraphPhase(id="P1", name="root", files=[], tests=[], depends_on=[]),
        TaskGraphPhase(id="P2", name="child", files=[], tests=[], depends_on=["P1"]),
    ]
    await manager.create_from_phases(phases, 42, tmp_path)
    issues = tmp_path / ".beads" / "issues.jsonl"
    records = [json.loads(line) for line in issues.read_text().splitlines()]
    if corruption == "missing":
        records = [
            record for record in records if not record["external_ref"].endswith(":P2")
        ]
    elif corruption == "duplicate":
        duplicate = dict(records[0])
        duplicate["id"] = "duplicate-id"
        records.append(duplicate)
    else:
        records[1]["dependencies"] = []
    original = "".join(json.dumps(record) + "\n" for record in records).encode()
    issues.write_bytes(original)

    with pytest.raises(RuntimeError, match=message):
        await manager.create_from_phases(phases, 42, tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
async def test_create_from_phases_unknown_dependency_is_transactional(
    manager, tmp_path
):
    issues = tmp_path / ".beads" / "issues.jsonl"
    issues.parent.mkdir()
    original = b'{"_type":"memory","key":"preserved"}\n'
    issues.write_bytes(original)
    phases = [
        TaskGraphPhase(id="P1", name="P1", files=[], tests=[], depends_on=["P0"]),
    ]

    with pytest.raises(KeyError, match="unknown dependencies"):
        await manager.create_from_phases(phases, 42, tmp_path)

    assert issues.read_bytes() == original


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "phases",
    [
        [TaskGraphPhase(id="P1", name="self", files=[], tests=[], depends_on=["P1"])],
        [
            TaskGraphPhase(
                id="P1", name="first", files=[], tests=[], depends_on=["P2"]
            ),
            TaskGraphPhase(
                id="P2", name="second", files=[], tests=[], depends_on=["P1"]
            ),
        ],
    ],
)
async def test_create_from_phases_rejects_cycles_without_overwrite(
    manager, tmp_path, phases
):
    with pytest.raises(RuntimeError, match="self-dependency|dependency cycle"):
        await manager.create_from_phases(phases, 42, tmp_path)

    assert not (tmp_path / ".beads").exists()


@pytest.mark.asyncio()
async def test_create_from_phases_rejects_duplicate_phase_ids(manager, tmp_path):
    phases = [
        TaskGraphPhase(id="P1", name="first", files=[], tests=[], depends_on=[]),
        TaskGraphPhase(id="P1", name="second", files=[], tests=[], depends_on=[]),
    ]

    with pytest.raises(ValueError, match="phase IDs must be unique"):
        await manager.create_from_phases(phases, 42, tmp_path)

    assert not (tmp_path / ".beads").exists()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_ready_json_with_deps():
    data = json.dumps(
        [
            {"id": "r-a1", "title": "Task A", "status": "open", "priority": 0},
            {
                "id": "r-b2",
                "title": "Task B",
                "status": "open",
                "priority": 1,
                "dependencies": [{"depends_on_id": "r-a1", "type": "blocks"}],
            },
        ]
    )
    tasks = BeadsManager._parse_ready_json(data)
    assert len(tasks) == 2
    assert tasks[0] == BeadTask(id="r-a1", title="Task A", status="open", priority=0)
    assert tasks[1].depends_on == ["r-a1"]


def test_parse_show_json_single():
    data = json.dumps(
        {"id": "r-a1", "title": "Task", "status": "closed", "priority": 0}
    )
    task = BeadsManager._parse_show_json(data)
    assert task is not None
    assert task.id == "r-a1"


def test_parse_show_json_empty_list():
    assert BeadsManager._parse_show_json("[]") is None


# ---------------------------------------------------------------------------
# State roundtrip
# ---------------------------------------------------------------------------


def test_bead_mapping_state_roundtrip(tmp_path):
    from state import StateTracker

    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)

    mapping = {"P1": "repo-4yu", "P2": "repo-z2o"}
    tracker.set_bead_mapping(42, mapping)
    assert tracker.get_bead_mapping(42) == mapping
    assert tracker.get_bead_mapping(999) == {}

    tracker2 = StateTracker(state_file)
    assert tracker2.get_bead_mapping(42) == mapping


# ===========================================================================
# Integration tests — planner leaves worktree task creation to implementation
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
    @pytest.mark.asyncio()
    async def test_planner_does_not_create_beads(self, config) -> None:
        """Beads are created by the IMPLEMENTER in its own worktree (not the
        planner), keeping factory JSONL state isolated from the host. The
        planner must NOT init/create beads or post a mapping comment, even when
        the plan contains a task graph."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        mock_beads.init.assert_not_awaited()
        mock_beads.create_from_phases.assert_not_awaited()
        assert state.get_bead_mapping(42) == {}
        bead_comments = [
            c for c in prs.post_comment.call_args_list if "Bead Task Mapping" in str(c)
        ]
        assert bead_comments == []


# ===========================================================================
# Integration tests — agent prompt with bead_mapping
# ===========================================================================


class TestAgentBeadPromptIntegration:
    @pytest.mark.asyncio
    async def test_injects_ids_without_database_cli_commands(
        self, config, event_bus
    ) -> None:
        from agent import AgentRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "repo-4yu", "P2": "repo-z2o"}
        )

        assert "**Bead:** #repo-4yu" in prompt
        assert "**Bead:** #repo-z2o" in prompt
        assert "Factory-owned JSONL record" in prompt
        assert "do not run `bd` in this worktree" in prompt
        assert "bd update" not in prompt
        assert "bd close" not in prompt

    @pytest.mark.asyncio
    async def test_no_commands_without_mapping(self, config, event_bus) -> None:
        from agent import AgentRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(issue, bead_mapping=None)

        assert "bd update" not in prompt
        assert "bd close" not in prompt

    @pytest.mark.asyncio
    async def test_partial_mapping(self, config, event_bus) -> None:
        from agent import AgentRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = await runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "repo-4yu"}
        )

        assert "**Bead:** #repo-4yu" in prompt
        assert "repo-z2o" not in prompt


# ===========================================================================
# Integration tests — implement_phase bead mapping passthrough
# ===========================================================================


class TestImplementPhaseBeadsIntegration:
    @pytest.mark.asyncio()
    async def test_mapping_write_failure_recovers_same_jsonl_graph(
        self, config, manager
    ) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        issue = TaskFactory.create(
            id=42,
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        phase, _wt, _prs = make_implement_phase(config, [issue])
        phase._beads_manager = manager
        worktree = config.workspace_path_for_issue(issue.id)
        worktree.mkdir(parents=True)

        with patch.object(
            phase._state,
            "set_bead_mapping",
            side_effect=OSError("state write interrupted"),
        ):
            first = await phase._create_beads_in_worktree(issue, worktree)
        second = await phase._create_beads_in_worktree(issue, worktree)

        records = [
            json.loads(line)
            for line in (worktree / ".beads" / "issues.jsonl").read_text().splitlines()
        ]
        issue_records = [record for record in records if record.get("_type") == "issue"]
        assert first == second
        assert len(issue_records) == 2
        assert {record["external_ref"] for record in issue_records} == {
            "hydraflow-factory:issue:42:phase:P1",
            "hydraflow-factory:issue:42:phase:P2",
        }

    @pytest.mark.asyncio()
    async def test_same_shaped_state_mapping_cannot_substitute_unrelated_tasks(
        self, config, manager
    ) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        issue = TaskFactory.create(
            id=42,
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        phase, _wt, _prs = make_implement_phase(config, [issue])
        phase._beads_manager = manager
        worktree = config.workspace_path_for_issue(issue.id)
        worktree.mkdir(parents=True)
        unrelated_root = await manager.create_task("unrelated root", "0", worktree)
        unrelated_child = await manager.create_task("unrelated child", "1", worktree)
        await manager.add_dependency(unrelated_child, unrelated_root, worktree)
        phase._state.set_bead_mapping(
            issue.id,
            {"P1": unrelated_root, "P2": unrelated_child},
        )

        mapping = await phase._create_beads_in_worktree(issue, worktree)

        assert mapping is not None
        assert set(mapping.values()).isdisjoint({unrelated_root, unrelated_child})
        assert phase._state.get_bead_mapping(issue.id) == mapping
        records = [
            json.loads(line)
            for line in (worktree / ".beads" / "issues.jsonl").read_text().splitlines()
        ]
        stable_records = [record for record in records if "external_ref" in record]
        assert {record["external_ref"] for record in stable_records} == {
            "hydraflow-factory:issue:42:phase:P1",
            "hydraflow-factory:issue:42:phase:P2",
        }

    @pytest.mark.asyncio()
    async def test_partial_root_claim_failure_reuses_created_graph(
        self, config
    ) -> None:
        from mockworld.fakes.fake_beads import FakeBeads
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        plan = (
            "## Task Graph\n\n"
            "### P1 — First root\n"
            "**Files:** src/one.py\n"
            "**Tests:**\n- first\n"
            "**Depends on:** (none)\n\n"
            "### P2 — Second root\n"
            "**Files:** src/two.py\n"
            "**Tests:**\n- second\n"
            "**Depends on:** (none)\n"
        )
        issue = TaskFactory.create(
            id=42,
            comments=["## Implementation Plan\n\n" + plan],
        )
        phase, _wt, _prs = make_implement_phase(config, [issue])
        beads = FakeBeads()
        original_claim = beads.claim
        claims = 0

        async def fail_second_claim(bead_id: str, cwd: Path) -> None:
            nonlocal claims
            claims += 1
            if claims == 2:
                raise OSError("claim interrupted")
            await original_claim(bead_id, cwd)

        beads.claim = fail_second_claim  # type: ignore[method-assign]
        phase._beads_manager = beads
        worktree = config.workspace_path_for_issue(issue.id)
        worktree.mkdir(parents=True)

        first = await phase._create_beads_in_worktree(issue, worktree)
        stored = phase._state.get_bead_mapping(issue.id)
        second = await phase._create_beads_in_worktree(issue, worktree)

        assert first == stored
        assert second == stored
        assert beads.task_count() == 2
        assert {task.status for task in beads._tasks.values()} == {"in_progress"}

    @pytest.mark.asyncio()
    async def test_passes_mapping_to_agent(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, workspace_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)
        # The implementer extracts phases from the on-disk plan and creates the
        # beads in THIS worktree, then passes the mapping to the agent.
        config.plans_dir.mkdir(parents=True, exist_ok=True)
        (config.plans_dir / "issue-42.md").write_text(_TASK_GRAPH_PLAN)

        mock_beads = AsyncMock()
        mock_beads.create_from_phases = AsyncMock(
            return_value={"P1": "repo-4yu", "P2": "repo-z2o"}
        )
        mock_beads.show = AsyncMock(
            side_effect=lambda bead_id, _cwd: BeadTask(
                id=bead_id,
                title=bead_id,
                status="open",
                priority=0,
            )
        )
        mock_beads.list_ready = AsyncMock(
            side_effect=[
                [
                    BeadTask(
                        id="repo-4yu",
                        title="P1",
                        status="in_progress",
                        priority=0,
                    )
                ],
                [BeadTask(id="repo-z2o", title="P2", status="open", priority=1)],
            ]
        )
        phase._beads_manager = mock_beads

        await phase.run_batch()

        mock_beads.init.assert_awaited_once()
        mock_beads.create_from_phases.assert_awaited_once()
        assert captured[0]["bead_mapping"] == {"P1": "repo-4yu", "P2": "repo-z2o"}
        assert phase._state.get_bead_mapping(42) == {"P1": "repo-4yu", "P2": "repo-z2o"}
        assert [call.args[0] for call in mock_beads.claim.await_args_list] == [
            "repo-4yu",
            "repo-z2o",
        ]
        assert [call.args[0] for call in mock_beads.close.await_args_list] == [
            "repo-4yu",
            "repo-z2o",
        ]
        phase._agents.commit_pending.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_final_state_commit_failure_blocks_success(self, config) -> None:
        from mockworld.fakes.fake_beads import FakeBeads
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        issue = TaskFactory.create(id=42)
        phase, _wt, prs = make_implement_phase(config, [issue])
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)
        config.plans_dir.mkdir(parents=True, exist_ok=True)
        (config.plans_dir / "issue-42.md").write_text(_TASK_GRAPH_PLAN)
        beads = FakeBeads()
        phase._beads_manager = beads
        phase._agents.commit_pending = AsyncMock(return_value=False)
        config.workspace_path_for_issue(issue.id).mkdir(parents=True)

        results, _ = await phase.run_batch()

        assert results[0].success is False
        assert results[0].error == "Failed to commit finalized worktree Beads lifecycle"
        prs.push_branch.assert_awaited_once()  # initial branch publication only
        prs.create_pr.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_no_mapping_without_manager(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, workspace_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        await phase.run_batch()
        assert "bead_mapping" not in captured[0]

    @pytest.mark.asyncio()
    async def test_no_mapping_without_plan(self, config) -> None:
        """No plan on disk → no phases → no beads created, no mapping passed."""
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, workspace_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)
        mock_beads = AsyncMock()
        phase._beads_manager = mock_beads
        # No plan file written for this issue → implementer creates no beads.

        await phase.run_batch()
        assert "bead_mapping" not in captured[0]
        mock_beads.init.assert_not_awaited()
        mock_beads.create_from_phases.assert_not_awaited()


# ===========================================================================
# Integration tests — reviewer per-bead review section
# ===========================================================================


class TestReviewerBeadPromptIntegration:
    @pytest.mark.asyncio
    async def test_adds_per_bead_section(self, config, event_bus) -> None:
        from reviewer import ReviewRunner
        from tests.conftest import PRInfoFactory, TaskFactory

        runner = ReviewRunner(config, event_bus)
        pr = PRInfoFactory.create(number=101, branch="agent/issue-42", issue_number=42)
        issue = TaskFactory.create(id=42, title="Add widget", body="Need widgets")
        diff = "diff --git a/src/models.py b/src/models.py\n+class Widget:\n"

        prompt, _ = await runner._build_review_prompt_with_stats(
            pr,
            issue,
            diff,
            bead_tasks=[
                {
                    "id": "repo-4yu",
                    "phase": "P1",
                    "status": "closed",
                    "files": "src/models.py",
                    "tests": "Widget persists",
                }
            ],
        )
        assert "## Per-Bead Review" in prompt
        assert "Bead #repo-4yu" in prompt

    @pytest.mark.asyncio
    async def test_no_section_without_tasks(self, config, event_bus) -> None:
        from reviewer import ReviewRunner
        from tests.conftest import PRInfoFactory, TaskFactory

        runner = ReviewRunner(config, event_bus)
        prompt, _ = await runner._build_review_prompt_with_stats(
            PRInfoFactory.create(number=101, branch="x", issue_number=42),
            TaskFactory.create(id=42, title="Fix", body="b"),
            "diff --git a/x b/x\n+y\n",
            bead_tasks=None,
        )
        assert "## Per-Bead Review" not in prompt


# ===========================================================================
# Integration tests — review_phase bead context builder
# ===========================================================================


class TestReviewPhaseBeadContext:
    def test_builds_context_from_mapping(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu", "P2": "repo-z2o"})

        issue = TaskFactory.create(
            id=42, title="Widget", body="body", comments=[_TASK_GRAPH_PLAN]
        )
        result = phase._build_bead_review_context(issue)

        assert result is not None
        assert len(result) == 2
        p1 = next(b for b in result if b["phase"] == "P1")
        assert p1["id"] == "repo-4yu"
        assert "src/models.py" in str(p1["files"])

    def test_none_when_no_mapping(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        assert (
            phase._build_bead_review_context(
                TaskFactory.create(id=999, title="T", body="b")
            )
            is None
        )

    def test_n_a_without_plan_comments(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu"})

        result = phase._build_bead_review_context(
            TaskFactory.create(id=42, title="T", body="b", comments=[])
        )
        assert result is not None
        assert result[0]["files"] == "N/A"
        assert result[0]["tests"] == "N/A"
