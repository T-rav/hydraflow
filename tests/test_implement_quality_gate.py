"""Implement-path quality gate (``src/implement_quality_gate.py``, #11568).

The implementer's post-build verification used to run the full ``make
quality``, which serializes every worker on the host-wide advisory lock
(``scripts/quality_host_lock.py``, #11400) — 10–15 min queued per
quality-fix round with three workers sharing one lock. The lock guards the
HOST (concurrent full suites thrash one box, #11219), so the implement path
now runs lock-free steps only: lint + typecheck + security, then the tests
the diff plausibly touches (bounded — never the whole suite). CI is the one
full-suite gate per PR. HITL / diagnostic runners keep the locked full run.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from agent import AgentRunner
from events import EventBus
from execution import SimpleResult
from implement_quality_gate import (
    IMPACTED_TEST_TARGET,
    QUALITY_LITE_COMMAND,
    impacted_test_command,
    run_gate_step,
)
from models import LoopResult


class _RecordingRunner:
    """SubprocessRunner fake: records argv, scripts the make-tier results.

    ``git`` commands answer ``"1"`` so ``_count_commits`` passes the
    zero-commit gate; everything else pops the next scripted result and
    defaults to success once the script is exhausted.
    """

    _is_fake_adapter = True

    def __init__(self, responses: Sequence[SimpleResult] = ()) -> None:
        self.commands: list[list[str]] = []
        self._responses: deque[SimpleResult] = deque(responses)

    async def run_simple(self, cmd: Sequence[str], **_kw: Any) -> SimpleResult:
        argv = list(cmd)
        self.commands.append(argv)
        if argv[0] == "git":
            return SimpleResult(stdout="1", returncode=0)
        if self._responses:
            return self._responses.popleft()
        return SimpleResult(stdout="ok", returncode=0)

    async def create_streaming_process(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError  # pragma: no cover — gate never streams

    async def cleanup(self) -> None:
        return None


class _RaisingRunner(_RecordingRunner):
    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self._exc = exc

    async def run_simple(self, cmd: Sequence[str], **kw: Any) -> SimpleResult:
        if list(cmd)[0] == "git":
            return await super().run_simple(cmd, **kw)
        self.commands.append(list(cmd))
        raise self._exc


_MAKEFILE_WITH_IMPACTED = (
    "quality-lite:\n\t@true\ntest:\n\t@true\ntest-impacted: deps\n\t@true\n"
)
_MAKEFILE_PLAIN = "quality-lite:\n\t@true\ntest:\n\t@true\n"


def _worktree(tmp_path: Path, makefile: str | None) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    if makefile is not None:
        (wt / "Makefile").write_text(makefile)
    return wt


def _make_cmds(rec: _RecordingRunner) -> list[list[str]]:
    return [c for c in rec.commands if c[0] != "git"]


async def _verify(config, event_bus: EventBus, rec: Any, wt: Path) -> LoopResult:
    runner = AgentRunner(config, event_bus, runner=rec)
    return await runner._verify_result(wt, "agent/issue-42")


@pytest.mark.asyncio
async def test_gate_runs_quality_lite_then_bounded_impacted_tests(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner()

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is True
    assert result.summary == "OK"
    assert _make_cmds(rec) == [
        ["make", "quality-lite"],
        [
            "make",
            "test-impacted",
            f"BASE_REF=origin/{config.base_branch()}",
            "IMPACTED_ARGS=--bounded",
        ],
    ]


@pytest.mark.asyncio
async def test_gate_never_spawns_the_host_locked_full_suite(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner()

    await _verify(config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED))

    assert ["make", "quality"] not in rec.commands
    assert not any("quality_host_lock" in " ".join(c) for c in rec.commands)


@pytest.mark.asyncio
async def test_gate_falls_back_to_test_command_without_impacted_target(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner()

    result = await _verify(config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_PLAIN))

    assert result.passed is True
    assert _make_cmds(rec) == [["make", "quality-lite"], ["make", "test"]]


@pytest.mark.asyncio
async def test_gate_fallback_honours_configured_test_command(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    cfg = config.model_copy(update={"test_command": "pytest tests/unit -q"})
    rec = _RecordingRunner()

    await _verify(cfg, event_bus, rec, _worktree(tmp_path, None))

    assert _make_cmds(rec) == [["make", "quality-lite"], ["pytest", "tests/unit", "-q"]]


@pytest.mark.asyncio
async def test_quality_lite_failure_short_circuits_before_tests(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner(
        [SimpleResult(stdout="src/x.py:1:1: E501 line too long", returncode=1)]
    )

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is False
    assert "`make quality-lite` failed" in result.summary
    assert "E501" in result.summary
    assert _make_cmds(rec) == [["make", "quality-lite"]]


@pytest.mark.asyncio
async def test_impacted_test_failure_names_the_test_step(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner(
        [
            SimpleResult(stdout="[lint OK]", returncode=0),
            SimpleResult(
                stdout="FAILED tests/test_x.py::test_y", stderr="", returncode=1
            ),
        ]
    )

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is False
    assert "`make test-impacted` failed" in result.summary
    assert "FAILED tests/test_x.py::test_y" in result.summary


@pytest.mark.asyncio
async def test_failure_output_is_truncated_to_error_output_max_chars(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RecordingRunner([SimpleResult(stdout="x" * 10_000, returncode=1)])

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is False
    assert len(result.summary) <= config.error_output_max_chars + 100


@pytest.mark.asyncio
async def test_full_gate_kill_switch_restores_locked_make_quality(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    cfg = config.model_copy(update={"implement_full_quality_gate": True})
    rec = _RecordingRunner()

    result = await _verify(
        cfg, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is True
    assert _make_cmds(rec) == [["make", "quality"]]


@pytest.mark.asyncio
async def test_step_timeout_names_the_step_and_budget(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RaisingRunner(TimeoutError())

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is False
    assert (
        f"make quality-lite timed out after {config.quality_timeout}s" in result.summary
    )


@pytest.mark.asyncio
async def test_make_not_found_is_reported_not_raised(
    config, event_bus: EventBus, tmp_path: Path
) -> None:
    rec = _RaisingRunner(FileNotFoundError("make"))

    result = await _verify(
        config, event_bus, rec, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    )

    assert result.passed is False
    assert "not found" in result.summary


def test_implement_full_quality_gate_defaults_off(config) -> None:
    """The lock-free gate is the default; the locked full run is the opt-in."""
    assert config.implement_full_quality_gate is False


# ── module surface (pure helpers) ───────────────────────────────────────────


def test_impacted_test_command_probes_the_worktree_makefile(
    config, tmp_path: Path
) -> None:
    assert impacted_test_command(
        config, _worktree(tmp_path, _MAKEFILE_WITH_IMPACTED)
    ) == [
        "make",
        IMPACTED_TEST_TARGET,
        f"BASE_REF=origin/{config.base_branch()}",
        "IMPACTED_ARGS=--bounded",
    ]


def test_impacted_test_command_falls_back_to_make_test_on_blank_test_command(
    config, tmp_path: Path
) -> None:
    cfg = config.model_copy(update={"test_command": "   "})
    assert impacted_test_command(cfg, _worktree(tmp_path, None)) == ["make", "test"]


@pytest.mark.asyncio
async def test_run_gate_step_passes_cwd_and_timeout_to_the_runner(
    tmp_path: Path,
) -> None:
    seen: dict[str, Any] = {}

    class _Runner(_RecordingRunner):
        async def run_simple(self, cmd: Sequence[str], **kw: Any) -> SimpleResult:
            seen.update(kw)
            return await super().run_simple(cmd, **kw)

    result = await run_gate_step(
        _Runner(), QUALITY_LITE_COMMAND, tmp_path, timeout=42, error_output_max_chars=10
    )

    assert result.passed is True
    assert seen == {"cwd": str(tmp_path), "timeout": 42}


@pytest.mark.asyncio
async def test_run_gate_step_joins_stdout_and_stderr_in_the_failure_tail(
    tmp_path: Path,
) -> None:
    rec = _RecordingRunner(
        [SimpleResult(stdout="out-line", stderr="err-line", returncode=2)]
    )

    result = await run_gate_step(
        rec, ["make", "test"], tmp_path, timeout=5, error_output_max_chars=3000
    )

    assert result.passed is False
    assert result.summary == "`make test` failed:\nout-line\nerr-line"
