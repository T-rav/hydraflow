"""Regression: a timed-out subprocess whose child already exited must surface
``TimeoutError`` (the intended failed-read signal), NOT ``ProcessLookupError``
from ``proc.kill()``.

Root cause (observed live: a gh-timeout storm crashed ~6 loops + the HITL
close/requeue actions): on timeout the reap calls ``proc.kill()``; if the
child already exited, ``proc.kill()`` raises ``ProcessLookupError``. In the
loop ``_communicate_bounded`` helpers the ``contextlib.suppress`` wrapped only
``proc.wait()`` (not ``proc.kill()``), and ``execution.run_simple`` had no
suppress at all — so the ``ProcessLookupError`` escaped and crashed the loop
iteration instead of the caller handling the timeout. See #9794 / #9814.

#9883 found the guard from #9794/#9816 had only reached a subset of the reap
sites sharing this shape: more ``_communicate_bounded`` helpers
(``memory_backlog_loop``, ``skill_prompt_eval_loop``, ``principles_audit_loop``;
``corpus_learning_loop`` was later migrated off raw gh to PRPort in #9932) plus
inline reaps in ``staging_bisect_loop``,
``contract_refresh_loop``, ``trust_fleet_sanity_loop`` and the MockWorld
``fake_subprocess_runner`` host path still killed the child outside the
``suppress``. The parametrized helper tests below pin the named helpers; the
AST sweep (``test_no_loop_reaps_proc_kill_outside_processlookup_suppress``)
pins the class fleet-wide across ``src/*_loop.py`` so a fifth site can't
regress silently — mirroring the ``communicate()``-bounding sweep in
``test_issue_9508.py``.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))


class _DeadProc:
    """Hangs on communicate() (so wait_for times out) and models an already-dead
    child: proc.kill() raises ProcessLookupError, like a real reaped child. A
    real asyncio Process always exposes a ``pid`` (used by the #9648 killpg reap
    path in execution.run_simple); the tests that exercise killpg model the
    process group as already-gone by patching os.killpg to raise."""

    returncode: int | None = None
    pid: int = 424242

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        await asyncio.sleep(5)  # longer than the patched timeout
        return (b"", b"")

    def kill(self) -> None:
        raise ProcessLookupError()  # child already exited

    async def wait(self) -> int:
        return 0


# #9554/#10028: flake_tracker_loop, rc_budget_loop, fake_coverage_auditor_loop,
# adr_touchpoint_auditor_loop, memory_backlog_loop, skill_prompt_eval_loop and
# principles_audit_loop each carried a copy-pasted ``_communicate_bounded``
# helper (the exact behavior this parametrized test pinned) — all seven were
# deleted when their raw ``asyncio.create_subprocess_exec`` sites migrated
# onto the shared bounded helper (``subprocess_util.run_subprocess``/
# ``run_subprocess_result``, which delegates to
# ``execution.HostRunner.run_simple``). The ProcessLookupError-vs-TimeoutError
# guarantee those per-file helpers pinned now lives ONCE in
# ``execution.HostRunner.run_simple`` — pinned immediately below by
# ``test_host_runner_run_simple_surfaces_timeout_not_processlookup`` — so this
# parametrized case was removed rather than updated to import a function that
# no longer exists in any of those modules. ``staging_bisect_loop._run_git``
# (the sole remaining raw spawn, excluded for cooperative-cancellation
# reasons) keeps its own inline reap via ``process_group.kill_process_group``,
# which never raises ProcessLookupError (guarded internally) — nothing left
# to pin at the loop layer for it either.


@pytest.mark.asyncio
async def test_host_runner_run_simple_surfaces_timeout_not_processlookup(monkeypatch):
    import execution

    async def _fake_create(*_a, **_kw):
        return _DeadProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)

    # #9648 changed the reap to os.killpg(proc.pid, SIGKILL). Model the process
    # group as already-gone so killpg raises ProcessLookupError, exactly like a
    # real reaped child. run_simple must still surface TimeoutError (the intended
    # failed-read signal), never the ProcessLookupError from the reap (#9794/#9814).
    def _dead_killpg(_pgid: int, _sig: int) -> None:
        raise ProcessLookupError()

    # execution.run_simple calls os.killpg on the shared os module, so patching
    # it here also patches the call inside run_simple.
    monkeypatch.setattr(os, "killpg", _dead_killpg)
    runner = execution.HostRunner()
    with pytest.raises(TimeoutError):
        await runner.run_simple(["gh", "issue", "list"], timeout=0.01)


@pytest.mark.asyncio
async def test_fake_subprocess_runner_host_reap_surfaces_timeout_not_processlookup(
    monkeypatch,
):
    """The MockWorld fake's host path (git/make run for real) must reap with the
    same guard — a real reaped child there raises ProcessLookupError too (#9883).

    Since #9624 the fake's ``_run_on_host`` delegates to ``HostRunner.run_simple``,
    so the timeout reap is the shared ``os.killpg`` group-kill. Model the process
    group as already-gone (killpg raises ProcessLookupError) so the reap never
    signals a real pgid that happens to match ``_DeadProc.pid``, exactly like the
    sibling HostRunner test above."""
    from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner

    async def _fake_create(*_a, **_kw):
        return _DeadProc()

    def _dead_killpg(_pgid: int, _sig: int) -> None:
        raise ProcessLookupError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create)
    monkeypatch.setattr(os, "killpg", _dead_killpg)
    with pytest.raises(TimeoutError):
        await FakeSubprocessRunner._run_on_host(["git", "status"], timeout=0.01)


# --------------------------------------------------------------------------- #
# Fleet-wide AST sweep: every ``proc.kill()`` in a background-loop file must sit
# inside a ``contextlib.suppress(ProcessLookupError)`` block, so the reap of an
# already-exited child surfaces the intended TimeoutError instead of crashing
# the loop cycle. Mirrors the ``communicate()``-bounding sweep in
# ``test_issue_9508.py`` so this gap class (#9794/#9816/#9883) can't recur
# silently in a new or edited loop.
# --------------------------------------------------------------------------- #


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _arg_name(arg: ast.expr) -> str | None:
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Attribute):
        return arg.attr
    return None


def _suppresses_processlookup(item: ast.withitem) -> bool:
    """True if a ``with`` item is ``contextlib.suppress(..., ProcessLookupError, ...)``."""
    expr = item.context_expr
    if not isinstance(expr, ast.Call) or _callee_name(expr.func) != "suppress":
        return False
    return any(_arg_name(a) == "ProcessLookupError" for a in expr.args)


class _UnguardedProcKillFinder(ast.NodeVisitor):
    """Collect line numbers of ``proc.kill()`` calls not lexically enclosed by a
    ``contextlib.suppress(ProcessLookupError)`` block."""

    def __init__(self) -> None:
        self.violations: list[int] = []
        self._guard_depth = 0

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        guarded = any(_suppresses_processlookup(item) for item in node.items)
        if guarded:
            self._guard_depth += 1
        self.generic_visit(node)
        if guarded:
            self._guard_depth -= 1

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "kill"
            and isinstance(func.value, ast.Name)
            and func.value.id == "proc"
            and self._guard_depth == 0
        ):
            self.violations.append(node.lineno)
        self.generic_visit(node)


def test_no_loop_reaps_proc_kill_outside_processlookup_suppress() -> None:
    offenders: dict[str, list[int]] = {}
    for path in sorted(SRC_DIR.rglob("*_loop.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        finder = _UnguardedProcKillFinder()
        finder.visit(tree)
        if finder.violations:
            offenders[str(path.relative_to(SRC_DIR))] = finder.violations

    assert not offenders, (
        "Background loops must reap a timed-out subprocess with `proc.kill()` "
        "inside `contextlib.suppress(ProcessLookupError)` — an already-exited "
        "child makes `proc.kill()` raise ProcessLookupError, which otherwise "
        "escapes and crashes the loop cycle instead of surfacing the intended "
        "TimeoutError (gh-timeout storm; #9794/#9816/#9883). "
        f"Unguarded proc.kill() sites: {offenders}"
    )
