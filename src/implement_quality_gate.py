"""Implement-path quality gate — lock-free post-build verification (#11568).

``make quality`` runs under a host-wide advisory lock
(``scripts/quality_host_lock.py``, #11400): two concurrent full suites on one
box oversubscribe it — xdist workers get killed mid-run and the survivor
reports failures that pass in isolation (#11219) — so the second run waits.
That lock guards the HOST, not the code. Routing the implementer's post-build
verification through it serialized every worker after every build and every
quality-fix round: 10–15 min queued per round with three workers on one
lock, while the dashboard reported ``max_workers`` parallelism the lock
removed (measured in #11568: implement attempts per issue 1.2 → 2.2).

Operator ruling 2026-08-21: take ``make quality`` off the host lock on the
implement path; CI (9–11 min) is the full gate. "Off the lock" does NOT mean
"N concurrent unlocked full suites" — that is the #11219 thrash the lock
exists to prevent. The implementer therefore never runs the full suite
locally:

1. ``make quality-lite`` — lint + typecheck + security, lock-free, minutes;
2. ``make test-impacted BASE_REF=origin/<base> IMPACTED_ARGS=--bounded`` —
   the tests the diff plausibly touches (``scripts/impacted_tests.py``);
   ``--bounded`` never expands to the whole suite — a high-fanout diff keeps
   its name-mapped tests plus the always-on floor and defers the full run to
   CI. Repos that do not declare the target run ``config.test_command``.

The HITL and diagnostic runners keep ``BaseRunner._verify_quality`` (the
locked full run): recovery work is one-at-a-time by design.
``config.implement_full_quality_gate`` restores the locked full run for the
implementer too; ``AgentRunner._verify_quality`` owns that switch.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from makefile_contract import makefile_targets
from models import LoopResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from execution import SubprocessRunner

#: HydraFlow-format repos declare this lock-free, diff-scoped test target.
IMPACTED_TEST_TARGET = "test-impacted"
#: Step 1 of the gate — the contract target every HydraFlow-format repo has.
QUALITY_LITE_COMMAND: tuple[str, ...] = ("make", "quality-lite")


def impacted_test_command(config: HydraFlowConfig, worktree_path: Path) -> list[str]:
    """Step 2 of the gate: bounded ``make test-impacted``, else ``test_command``.

    The ``test-impacted`` target is HydraFlow-specific, so it is probed in
    the worktree's Makefile rather than assumed; a repo without it gets its
    own configured quick test command (the one the implementer prompt
    already tells the agent to run).
    """
    if IMPACTED_TEST_TARGET in makefile_targets(worktree_path):
        return [
            "make",
            IMPACTED_TEST_TARGET,
            f"BASE_REF=origin/{config.base_branch()}",
            "IMPACTED_ARGS=--bounded",
        ]
    return shlex.split(config.test_command) or ["make", "test"]


async def run_gate_step(
    runner: SubprocessRunner,
    cmd: Sequence[str],
    worktree_path: Path,
    *,
    timeout: int,
    error_output_max_chars: int,
) -> LoopResult:
    """Run one gate command in the worktree with the ``_verify_quality`` envelope.

    Same failure shapes as ``BaseRunner._verify_quality`` (missing tool,
    timeout, non-zero exit with the output tail) so the quality-fix prompt
    and ``worker_result_meta`` consumers see one contract; the summary names
    the step so a fix round targets the right failure.
    """
    argv = list(cmd)
    label = " ".join(argv[:2])
    try:
        result = await runner.run_simple(argv, cwd=str(worktree_path), timeout=timeout)
    except FileNotFoundError:
        return LoopResult(
            passed=False, summary=f"{argv[0]} not found — cannot run `{label}`"
        )
    except TimeoutError:
        return LoopResult(passed=False, summary=f"{label} timed out after {timeout}s")
    if result.returncode != 0:
        output = "\n".join(filter(None, [result.stdout, result.stderr]))
        return LoopResult(
            passed=False,
            summary=f"`{label}` failed:\n{output[-error_output_max_chars:]}",
        )
    return LoopResult(passed=True, summary="OK")


async def run_implement_quality_gate(
    runner: SubprocessRunner, config: HydraFlowConfig, worktree_path: Path
) -> LoopResult:
    """The implementer's post-build gate: quality-lite, then the impacted tests.

    Short-circuits on the first red step — a lint/type failure is cheaper to
    fix before spending the test run, and the fix prompt only needs one
    failure at a time.
    """
    lite = await run_gate_step(
        runner,
        QUALITY_LITE_COMMAND,
        worktree_path,
        timeout=config.quality_timeout,
        error_output_max_chars=config.error_output_max_chars,
    )
    if not lite.passed:
        return lite
    return await run_gate_step(
        runner,
        impacted_test_command(config, worktree_path),
        worktree_path,
        timeout=config.quality_timeout,
        error_output_max_chars=config.error_output_max_chars,
    )
