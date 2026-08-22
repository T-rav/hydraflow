"""Regression pins for #11568 — the implement path is off the host quality lock.

Since #11400 ``make quality`` runs under a host-wide advisory lock
(``scripts/quality_host_lock.py``): two concurrent full suites on one box
oversubscribe it, xdist workers get killed mid-run and the survivor reports
failures that pass in isolation (#11219), so the second run WAITS. That is
the right guard for the HOST — but ``AgentRunner._verify_result`` ran the
full, locked target after every build and after every quality-fix round, so
``max_workers`` implementers serialized on one lock: 10–15 min queued per
round while the dashboard reported parallelism the lock removed (measured
in #11568: implement attempts per issue 1.2 → 2.2). Operator ruling
2026-08-21: take ``make quality`` off the host lock on the implement path;
CI (9–11 min) is the full gate.

Pinned here:

1. the implementer's gate never spawns ``make quality`` — lint + typecheck +
   security, then the BOUNDED impacted-test run, both lock-free;
2. the operator/recovery runners (HITL, diagnostic), the Makefile's
   ``quality`` target and the pre-push hook are unchanged — those paths are
   one-at-a-time by design and still queue on the lock;
3. the bounded selector never emits the full-suite sentinel, so a
   high-fanout diff cannot smuggle an unlocked full suite back in.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from agent import AgentRunner
from base_runner import BaseRunner
from diagnostic_runner import DiagnosticRunner
from events import EventBus
from execution import SimpleResult
from hitl_runner import HITLRunner
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Same by-path load idiom as tests/test_impacted_tests.py — scripts/ is not
# an importable package from the tests root.
_MODULE_PATH = _REPO_ROOT / "scripts" / "impacted_tests.py"
_spec = importlib.util.spec_from_file_location("impacted_tests", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
impacted_tests = importlib.util.module_from_spec(_spec)
sys.modules["impacted_tests"] = impacted_tests
_spec.loader.exec_module(impacted_tests)


class _RecordingRunner:
    _is_fake_adapter = True

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run_simple(self, cmd: Sequence[str], **_kw: Any) -> SimpleResult:
        self.commands.append(list(cmd))
        return SimpleResult(stdout="1", returncode=0)

    async def create_streaming_process(self, *_a: Any, **_k: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def cleanup(self) -> None:
        return None


def _config(tmp_path: Path, **overrides: Any):
    cfg = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    return cfg.model_copy(update=overrides) if overrides else cfg


def _worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "Makefile").write_text("quality-lite:\n\t@true\ntest-impacted:\n\t@true\n")
    return wt


async def test_implementer_gate_never_spawns_host_locked_make_quality(
    tmp_path: Path,
) -> None:
    rec = _RecordingRunner()
    runner = AgentRunner(_config(tmp_path), EventBus(), runner=rec)

    result = await runner._verify_result(_worktree(tmp_path), "agent/issue-1")

    assert result.passed is True
    make_cmds = [c for c in rec.commands if c[0] == "make"]
    assert ["make", "quality"] not in make_cmds
    assert make_cmds[0] == ["make", "quality-lite"]
    assert make_cmds[1][:2] == ["make", "test-impacted"]
    assert "IMPACTED_ARGS=--bounded" in make_cmds[1]


async def test_quality_fix_loop_reverifies_through_the_lock_free_gate(
    tmp_path: Path,
) -> None:
    """Every fix round used to queue on the lock again — the round is the unit of waste."""
    rec = _RecordingRunner()
    runner = AgentRunner(_config(tmp_path), EventBus(), runner=rec)
    wt = _worktree(tmp_path)
    with (
        patch.object(runner, "_execute", new_callable=AsyncMock, return_value=""),
        patch.object(runner, "_force_commit_uncommitted", new_callable=AsyncMock),
    ):
        fix = await runner._run_quality_fix_loop(
            TaskFactory.create(), wt, "agent/issue-1", "ruff: E501", worker_id=0
        )

    assert fix.passed is True
    assert ["make", "quality"] not in rec.commands
    assert ["make", "quality-lite"] in rec.commands


async def test_operator_runners_still_run_the_locked_full_suite(tmp_path: Path) -> None:
    """HITL and diagnostic runs are one-at-a-time recovery work: the lock stays."""
    for cls in (HITLRunner, DiagnosticRunner):
        rec = _RecordingRunner()
        runner = cls(_config(tmp_path), EventBus(), runner=rec)
        # Through the instance, not ``BaseRunner._verify_quality(runner, …)``:
        # a future override on either runner must trip the argv pin below.
        result = await runner._verify_quality(tmp_path)
        assert result.passed is True, cls.__name__
        assert rec.commands == [["make", "quality"]], cls.__name__
        assert type(runner)._verify_quality is BaseRunner._verify_quality, cls.__name__


def test_makefile_quality_target_still_routes_through_the_host_lock() -> None:
    text = (_REPO_ROOT / "Makefile").read_text()
    recipe = text[
        text.index("quality: deps lint-ul") : text.index("\nquality-unlocked:")
    ]
    assert "scripts/quality_host_lock.py" in recipe


def test_pre_push_hook_runs_quality_lite_not_the_full_suite() -> None:
    hook = (_REPO_ROOT / ".githooks" / "pre-push").read_text()
    assert "make quality-lite" in hook
    assert not re.search(r"^\s*make quality\s*$", hook, re.MULTILINE)


def test_bounded_selector_never_emits_the_full_suite_sentinel() -> None:
    fs = impacted_tests.InMemoryFileIndex(
        frozenset(
            {
                "src/config.py",
                "tests/test_config_core.py",
                "tests/architecture/test_a.py",
            }
        )
    )
    for changed in (
        ["src/config.py"],
        ["Makefile"],
        ["tests/helpers.py"],
        ["src/unmapped.py"],
    ):
        result = impacted_tests.select_tests(changed, fs, bounded=True)
        assert result.full_suite is False, changed
        assert result.test_files, changed
