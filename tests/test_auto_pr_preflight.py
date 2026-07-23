"""Tests for the auto_pr pre-flight quality-lite gate (#10013).

The gate runs inside the ephemeral PR worktree after generate+stage and
before commit/push/``gh pr create``. A red stage blocks the PR entirely:
no commit, no push, no ``gh pr create``. Stages are selectable per
call-site via the ``preflight`` parameter; docs-only callers pass
``PREFLIGHT_DOCS_ONLY``.

Subprocess strategy mirrors ``tests/test_auto_pr.py``: git runs for real
against a scratch repo + bare remote, ``gh pr`` calls are intercepted, and
the gate's tool invocations (``uv run …``) are intercepted so no venv sync
or pytest run happens in unit tests. The end-to-end red path with a real
pytest run lives in ``tests/regressions/test_auto_pr_preflight_gate.py``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare git repo that acts as 'origin' for tests."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """A checkout of the bare remote, with one initial commit on main."""
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "t"], check=True)
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(local), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


ToolHandler = Callable[[tuple[str, ...]], str | None]


def _stub_run_subprocess(
    calls: list[tuple[str, ...]],
    tool_handler: ToolHandler | None = None,
) -> Callable[..., Awaitable[str]]:
    """Fake ``run_subprocess``: real git, intercepted gh + gate tools.

    - Every command is appended to ``calls``.
    - ``gh …`` commands return a canned PR URL (create) or empty output.
    - Gate tool commands (first token ``uv``) route through ``tool_handler``;
      a returned string is the command's stdout, ``None`` means success with
      empty output, and a raised exception propagates (a red stage).
    - Everything else (git) executes for real against the scratch repo.
    """

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, runner
        calls.append(tuple(cmd))
        if cmd[0] == "gh":
            if cmd[:3] == ("gh", "pr", "create"):
                return "https://github.com/x/y/pull/7"
            return ""
        if cmd[0] == "uv":
            if tool_handler is not None:
                out = tool_handler(tuple(cmd))
                return out or ""
            return ""
        del timeout
        try:
            return subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


def _seed_gate_targets(repo: Path) -> None:
    """Commit ratchet-test + arch-runner marker files so no stage self-skips."""
    (repo / "tests").mkdir()
    (repo / "tests" / "test_disturbance_ratchet.py").write_text(
        "def test_placeholder() -> None:\n    pass\n"
    )
    (repo / "src" / "arch").mkdir(parents=True)
    (repo / "src" / "arch" / "runner.py").write_text("print('check')\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed gate"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "origin", "main"], check=True)


async def _open_pr_with_generated_module(
    local_repo: Path,
    *,
    preflight: tuple[str, ...] | None = None,
    raise_on_failure: bool = False,
):
    """Drive generate_and_open_pr_async staging one generated .py file."""
    from auto_pr import generate_and_open_pr_async

    async def _generate(worktree: Path) -> None:
        (worktree / "widget.py").write_text("WIDGET = 1\n")

    if preflight is not None:
        return await generate_and_open_pr_async(
            repo_root=local_repo,
            branch="bot/gate-check",
            generate=_generate,
            path_specs=["widget.py"],
            pr_title="chore: widget",
            pr_body="body",
            raise_on_failure=raise_on_failure,
            preflight=preflight,
        )
    return await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="bot/gate-check",
        generate=_generate,
        path_specs=["widget.py"],
        pr_title="chore: widget",
        pr_body="body",
        raise_on_failure=raise_on_failure,
    )


def _gate_tool_calls(calls: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return [c for c in calls if c[0] == "uv"]


@pytest.mark.asyncio
async def test_default_gate_runs_pytest_arch_ruff_before_pr_create(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full default set: pytest ratchet+regressions, arch --check, ruff run
    inside the worktree, all before any gh pr create."""
    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("subprocess_util.run_subprocess", _stub_run_subprocess(calls))

    result = await _open_pr_with_generated_module(local_repo)

    assert result.status == "opened"
    tool_calls = _gate_tool_calls(calls)
    assert len(tool_calls) == 3
    pytest_cmd, arch_cmd, ruff_cmd = tool_calls
    assert "pytest" in pytest_cmd
    assert "tests/test_disturbance_ratchet.py" in pytest_cmd
    assert "arch.runner" in arch_cmd
    assert "--check" in arch_cmd
    assert "ruff" in ruff_cmd
    assert "widget.py" in ruff_cmd
    create_idx = calls.index(next(c for c in calls if c[:3] == ("gh", "pr", "create")))
    last_tool_idx = max(calls.index(c) for c in tool_calls)
    assert last_tool_idx < create_idx


@pytest.mark.asyncio
async def test_red_stage_blocks_pr_and_names_stage(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A red pytest stage yields status=failed + preflight_stage, and neither
    commit, push, nor gh pr create ever runs."""
    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []

    def red_pytest(cmd: tuple[str, ...]) -> str | None:
        if "pytest" in cmd:
            raise RuntimeError("1 failed: suppression count exceeded baseline")
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub_run_subprocess(calls, tool_handler=red_pytest),
    )

    result = await _open_pr_with_generated_module(local_repo)

    assert result.status == "failed"
    assert result.preflight_stage == "pytest"
    assert result.error is not None
    assert "pytest" in result.error
    assert not any(c[0] == "gh" for c in calls)
    assert not any(c[0] == "git" and "commit" in c for c in calls)
    assert not any(c[0] == "git" and "push" in c for c in calls)
    # Red short-circuits: later stages never run.
    assert len(_gate_tool_calls(calls)) == 1


@pytest.mark.asyncio
async def test_red_stage_raises_autoprerror_when_raise_on_failure(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_pr import AutoPrError

    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []

    def red_arch(cmd: tuple[str, ...]) -> str | None:
        if "arch.runner" in cmd:
            raise RuntimeError("generated artifacts are stale")
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub_run_subprocess(calls, tool_handler=red_arch),
    )

    with pytest.raises(AutoPrError, match="stage=arch"):
        await _open_pr_with_generated_module(local_repo, raise_on_failure=True)
    assert not any(c[:3] == ("gh", "pr", "create") for c in calls)


@pytest.mark.asyncio
async def test_docs_only_set_runs_only_ruff(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PREFLIGHT_DOCS_ONLY skips the pytest and arch stages entirely."""
    from auto_pr import PREFLIGHT_DOCS_ONLY

    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("subprocess_util.run_subprocess", _stub_run_subprocess(calls))

    result = await _open_pr_with_generated_module(
        local_repo, preflight=tuple(PREFLIGHT_DOCS_ONLY)
    )

    assert result.status == "opened"
    tool_calls = _gate_tool_calls(calls)
    assert len(tool_calls) == 1
    assert "ruff" in tool_calls[0]
    assert not any("pytest" in c for c in tool_calls)
    assert not any("arch.runner" in c for c in tool_calls)


@pytest.mark.asyncio
async def test_stages_self_skip_when_targets_missing(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a repo without ratchet tests or arch runner, staging only non-Python
    files, every stage self-skips — the gate must not red a wiki-style PR or a
    managed repo that lacks HydraFlow's gate targets."""
    from auto_pr import generate_and_open_pr_async

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("subprocess_util.run_subprocess", _stub_run_subprocess(calls))

    async def _generate(worktree: Path) -> None:
        (worktree / "docs").mkdir()
        (worktree / "docs" / "note.md").write_text("hello\n")

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="bot/docs-note",
        generate=_generate,
        path_specs=["docs"],
        pr_title="docs: note",
        pr_body="body",
        raise_on_failure=False,
    )

    assert result.status == "opened"
    assert _gate_tool_calls(calls) == []


@pytest.mark.asyncio
async def test_kill_switch_disables_gate(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """auto_pr_preflight_gate_enabled=False on the active config skips every
    stage even with the full default set and all targets present."""
    from config import HydraFlowConfig
    from trace_collector import set_active_config

    _seed_gate_targets(local_repo)
    cfg = HydraFlowConfig()
    object.__setattr__(cfg, "auto_pr_preflight_gate_enabled", False)
    set_active_config(cfg)
    try:
        calls: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            "subprocess_util.run_subprocess", _stub_run_subprocess(calls)
        )
        result = await _open_pr_with_generated_module(local_repo)
    finally:
        set_active_config(None)

    assert result.status == "opened"
    assert _gate_tool_calls(calls) == []


@pytest.mark.asyncio
async def test_stage_timeout_knob_is_threaded_to_run_subprocess(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import HydraFlowConfig
    from trace_collector import set_active_config

    _seed_gate_targets(local_repo)
    cfg = HydraFlowConfig()
    object.__setattr__(cfg, "auto_pr_preflight_stage_timeout_s", 123)
    set_active_config(cfg)

    seen_timeouts: list[float] = []
    calls: list[tuple[str, ...]] = []
    inner = _stub_run_subprocess(calls)

    async def capturing_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        if cmd[0] == "uv":
            seen_timeouts.append(timeout)
        return await inner(
            *cmd, cwd=cwd, gh_token=gh_token, timeout=timeout, runner=runner
        )

    monkeypatch.setattr("subprocess_util.run_subprocess", capturing_run)
    try:
        result = await _open_pr_with_generated_module(local_repo)
    finally:
        set_active_config(None)

    assert result.status == "opened"
    assert seen_timeouts
    assert all(t == 123.0 for t in seen_timeouts)


@pytest.mark.asyncio
async def test_sibling_open_automated_pr_async_is_gated_too(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file-copy sibling flows through the same gate: a red ruff stage on
    a staged .py file blocks the PR."""
    from auto_pr import open_automated_pr_async

    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []

    def red_ruff(cmd: tuple[str, ...]) -> str | None:
        if "ruff" in cmd:
            raise RuntimeError("E501 line too long")
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub_run_subprocess(calls, tool_handler=red_ruff),
    )

    target = local_repo / "gadget.py"
    target.write_text("GADGET = 2\n")

    result = await open_automated_pr_async(
        repo_root=local_repo,
        branch="bot/gadget",
        files=[target],
        pr_title="feat: gadget",
        pr_body="body",
        raise_on_failure=False,
        preflight=("ruff",),
    )

    assert result.status == "failed"
    assert result.preflight_stage == "ruff"
    assert not any(c[:3] == ("gh", "pr", "create") for c in calls)


@pytest.mark.asyncio
async def test_red_stage_error_recovers_stdout_from_chained_cause(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_subprocess's message carries stderr only; the gate must surface the
    stdout tail (where pytest/ruff report failures) from the chained
    CalledProcessError so operators see WHICH check went red."""
    _seed_gate_targets(local_repo)
    calls: list[tuple[str, ...]] = []

    def red_pytest_with_stdout(cmd: tuple[str, ...]) -> str | None:
        if "pytest" in cmd:
            cause = subprocess.CalledProcessError(
                1,
                list(cmd),
                output="FAILED tests/test_disturbance_ratchet.py::test_budget",
                stderr="",
            )
            raise RuntimeError("Command failed (rc=1): ") from cause
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub_run_subprocess(calls, tool_handler=red_pytest_with_stdout),
    )

    result = await _open_pr_with_generated_module(local_repo)

    assert result.status == "failed"
    assert result.error is not None
    assert "test_disturbance_ratchet.py::test_budget" in result.error


@pytest.mark.asyncio
async def test_ruff_stage_lints_only_staged_python_files(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_pr import generate_and_open_pr_async

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("subprocess_util.run_subprocess", _stub_run_subprocess(calls))

    async def _generate(worktree: Path) -> None:
        (worktree / "mod.py").write_text("MOD = 3\n")
        (worktree / "data.json").write_text("{}\n")

    result = await generate_and_open_pr_async(
        repo_root=local_repo,
        branch="bot/mixed",
        generate=_generate,
        path_specs=["mod.py", "data.json"],
        pr_title="chore: mixed",
        pr_body="body",
        raise_on_failure=False,
        preflight=("ruff",),
    )

    assert result.status == "opened"
    (ruff_cmd,) = _gate_tool_calls(calls)
    assert "mod.py" in ruff_cmd
    assert "data.json" not in ruff_cmd
