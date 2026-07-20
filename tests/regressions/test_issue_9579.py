"""Regression #9579: heavy-make caretaker loops orphaned subprocess
grandchildren on timeout.

The four heavy-make sites (``skill_prompt_eval_loop``,
``principles_audit_loop``, ``contract_refresh_loop``,
``staging_bisect_loop``) spawned ``make``/pytest/LLM subtrees WITHOUT
``start_new_session=True`` and reaped a timeout with a child-only
``proc.kill()`` — the top-level ``make`` died, its sub-make → pytest →
LLM-agent grandchildren re-parented to init (PPID=1) and kept burning API
credits against an abandoned cycle.

Fix shape (#10017's guarded primitive, no local killpg re-derivation):

* every heavy spawn passes ``start_new_session=True`` (child is its own
  process-group leader, ``pid == pgid``);
* every timeout/cancel reap routes through
  ``process_group.kill_process_group`` (guarded: real-int-pid only, mock
  fakes fall back to child-only ``proc.kill()``, never raises).

Three layers below:

1. AST pin — the spawn sites carry ``start_new_session=True`` and the reap
   paths call ``kill_process_group`` (no bare ``proc.kill()`` regression);
2. behavior pin — the shared ``_communicate_bounded`` helpers invoke the
   primitive on timeout and still surface ``TimeoutError``;
3. end-to-end — a REAL child that forks a grandchild into its group is
   reaped grandchild-and-all by a converted helper.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

# (module, function) → every asyncio.create_subprocess_exec inside must
# carry start_new_session=True. These are the heavy-make / heavy-subtree
# spawn sites named by #9579 (staging_bisect._run_git runs
# `git bisect run make bisect-probe`, a per-step make → pytest subtree).
_HEAVY_SPAWN_SITES = [
    ("skill_prompt_eval_loop", "_run_corpus"),
    ("skill_prompt_eval_loop", "_validate_candidate"),
    ("principles_audit_loop", "_run_audit"),
    ("principles_audit_loop", "_run_git"),
    ("contract_refresh_loop", "_run_replay_gate"),
    ("staging_bisect_loop", "_run_bisect_probe"),
    ("staging_bisect_loop", "_run_git"),
]

# (module, function) → the timeout/cancel reap inside must route through
# the guarded primitive (a `kill_process_group(...)` call) and must not
# fall back to a child-only bare `proc.kill()`.
_GROUP_REAP_SITES = [
    ("skill_prompt_eval_loop", "_communicate_bounded"),
    ("principles_audit_loop", "_communicate_bounded"),
    ("contract_refresh_loop", "_run_replay_gate"),
    ("staging_bisect_loop", "_run_bisect_probe"),
    ("staging_bisect_loop", "_run_git"),
]


def _find_function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    raise AssertionError(f"function {name!r} not found — site renamed? Update pins.")


def _module_tree(module_name: str) -> ast.AST:
    path = SRC_DIR / f"{module_name}.py"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize(("module_name", "func_name"), _HEAVY_SPAWN_SITES)
def test_heavy_spawn_sites_start_a_new_session(
    module_name: str, func_name: str
) -> None:
    func = _find_function(_module_tree(module_name), func_name)
    spawns = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_subprocess_exec"
    ]
    assert spawns, (
        f"{module_name}.{func_name} no longer spawns via create_subprocess_exec "
        "— update the #9579 pins to the new spawn path."
    )
    for call in spawns:
        kwargs = {k.arg: k.value for k in call.keywords if k.arg is not None}
        sns = kwargs.get("start_new_session")
        assert isinstance(sns, ast.Constant) and sns.value is True, (
            f"{module_name}.{func_name}:{call.lineno} spawns without "
            "start_new_session=True — the child is not a process-group "
            "leader, so the timeout reap kills only the direct child and "
            "orphans the make/pytest/LLM grandchildren at PPID=1 where they "
            "burn API credits (#9579)."
        )


@pytest.mark.parametrize(("module_name", "func_name"), _GROUP_REAP_SITES)
def test_heavy_reap_sites_use_the_guarded_group_primitive(
    module_name: str, func_name: str
) -> None:
    func = _find_function(_module_tree(module_name), func_name)
    calls_primitive = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "kill_process_group"
        for node in ast.walk(func)
    )
    assert calls_primitive, (
        f"{module_name}.{func_name} no longer reaps via "
        "process_group.kill_process_group — a child-only proc.kill() "
        "re-introduces the #9579 orphaned-grandchildren leak. Do NOT inline "
        "os.killpg either: the guard in the primitive is load-bearing "
        "(see tests/architecture/test_process_group_kill_guard.py)."
    )
    bare_kills = [
        node.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "kill"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "proc"
    ]
    assert not bare_kills, (
        f"{module_name}.{func_name} lines {bare_kills}: bare proc.kill() "
        "alongside the group primitive — the child-only path is exactly the "
        "#9579 regression."
    )


class _HangingProc:
    """communicate() outlives any test timeout; pid=None keeps the guarded
    primitive on its child-only fallback if it is ever reached for real
    (never signal a fabricated pid — mock .pid → killpg(1) kills CI)."""

    returncode: int | None = None
    pid: None = None

    def __init__(self) -> None:
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(30)
        return (b"", b"")

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return -9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module_name", ["skill_prompt_eval_loop", "principles_audit_loop"]
)
async def test_communicate_bounded_reaps_the_group_on_timeout(
    monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    """On timeout the shared helper must invoke the GROUP primitive exactly
    once and still surface TimeoutError (the intended failed-read signal)."""
    module = __import__(module_name)
    reaped: list[object] = []

    def _record_reap(proc: object) -> None:
        reaped.append(proc)

    monkeypatch.setattr(module, "kill_process_group", _record_reap)
    proc = _HangingProc()
    with pytest.raises(TimeoutError):
        await module._communicate_bounded(proc, timeout=0.01)
    assert reaped == [proc], (
        "timeout must route through process_group.kill_process_group "
        "(group reap), not a child-only proc.kill()"
    )
    assert not proc.killed, (
        "child-only proc.kill() was called from the loop helper — the group "
        "primitive owns the fallback decision (#9579)"
    )


_CHILD_SCRIPT = """
import subprocess, sys, time

# Grandchild joins THIS child's (new) session/process group — the exact
# shape of make -> pytest under a caretaker loop.
grandchild = subprocess.Popen(["sleep", "300"])
with open(sys.argv[1], "w") as fh:
    fh.write(str(grandchild.pid))
time.sleep(300)
"""


@pytest.mark.asyncio
async def test_timed_out_heavy_subtree_reaps_grandchildren(
    tmp_path: Path,
) -> None:
    """End-to-end #9579: a converted helper must kill the GRANDCHILD, not
    just the direct child, when the heavy subtree times out."""
    from principles_audit_loop import _communicate_bounded

    pid_file = tmp_path / "grandchild.pid"
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CHILD_SCRIPT,
        str(pid_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # as the production spawn sites now do
    )
    grandchild_pid: int | None = None
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if pid_file.exists() and pid_file.read_text().strip():
                grandchild_pid = int(pid_file.read_text().strip())
                break
            await asyncio.sleep(0.05)
        assert grandchild_pid is not None, "child never reported its grandchild pid"

        with pytest.raises(TimeoutError):
            await _communicate_bounded(proc, timeout=0.2)

        # SIGKILL delivery + init reaping are asynchronous — poll briefly.
        deadline = time.monotonic() + 5.0
        grandchild_dead = False
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild_pid, 0)
            except ProcessLookupError:
                grandchild_dead = True
                break
            await asyncio.sleep(0.1)
        assert grandchild_dead, (
            f"grandchild sleep(300) [pid {grandchild_pid}] survived the "
            "timeout reap — the #9579 orphaned-subtree leak is back"
        )
    finally:
        # Belt-and-braces: never leak the subtree out of the test run.
        from process_group import kill_process_group

        kill_process_group(proc)
        if grandchild_pid is not None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.kill(grandchild_pid, 9)
        with contextlib.suppress(ProcessLookupError, OSError):
            await proc.wait()
