"""Regression #9579: heavy-make caretaker loops orphaned subprocess
grandchildren on timeout.

The four heavy-make sites (``skill_prompt_eval_loop``,
``principles_audit_loop``, ``contract_refresh_loop``,
``staging_bisect_loop``) spawned ``make``/pytest/LLM subtrees WITHOUT
``start_new_session=True`` and reaped a timeout with a child-only
``proc.kill()`` — the top-level ``make`` died, its sub-make → pytest →
LLM-agent grandchildren re-parented to init (PPID=1) and kept burning API
credits against an abandoned cycle.

Original fix shape (#10017's guarded primitive, no local killpg
re-derivation): every heavy spawn passed ``start_new_session=True`` and every
timeout/cancel reap routed through ``process_group.kill_process_group``
directly in each loop file.

**#9554/#10028 follow-up:** every one of those sites except
``staging_bisect_loop._run_git`` has since migrated onto the shared bounded
helper (``subprocess_util.run_subprocess``/``run_subprocess_result``, which
delegates to ``execution.HostRunner.run_simple``) — the per-file
``_communicate_bounded`` copies and local raw
``asyncio.create_subprocess_exec`` + ``start_new_session=True`` +
``kill_process_group`` triplets are gone. The #9579 guarantee (group-leader
spawn, group-kill reap on timeout) now lives ONCE in
``execution.HostRunner.run_simple`` — pinned end-to-end with a real
subprocess+grandchild by ``tests/regressions/test_hostrunner_reap_grandchildren.py``
(#9648) — rather than being re-derived per loop. ``staging_bisect_loop._run_git``
is the sole survivor here: its mid-run ``enabled_cb`` polling for cooperative
kill-switch cancellation cannot be expressed through the shared helper (see
``tests/regressions/test_issue_9508.py`` / the #9554 migration notes), so it
keeps its own local spawn + reap and remains pinned below.

Two layers below (for the one surviving raw site):

1. AST pin — the spawn carries ``start_new_session=True`` and the reap path
   calls ``kill_process_group`` (no bare ``proc.kill()`` regression);
2. end-to-end — a REAL child that forks a grandchild into its group is
   reaped grandchild-and-all.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

# (module, function) → every asyncio.create_subprocess_exec inside must
# carry start_new_session=True. ``staging_bisect_loop._run_git`` is the sole
# remaining raw heavy spawn (see module docstring) — every other #9579 site
# migrated onto the shared bounded helper (#9554/#10028) and is pinned
# instead by each loop's own test file + tests/test_subprocess_util.py +
# tests/regressions/test_hostrunner_reap_grandchildren.py.
_HEAVY_SPAWN_SITES = [
    ("staging_bisect_loop", "_run_git"),
]

# (module, function) → the timeout/cancel reap inside must route through
# the guarded primitive (a `kill_process_group(...)` call) and must not
# fall back to a child-only bare `proc.kill()`.
_GROUP_REAP_SITES = [
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


# --- Behavior + end-to-end pins for the migrated sites ---------------------
#
# `skill_prompt_eval_loop`/`principles_audit_loop` no longer define a local
# `_communicate_bounded` (deleted by #9554/#10028 — they route through
# `subprocess_util.run_subprocess_result`/`run_subprocess`, which delegates to
# `execution.HostRunner.run_simple`), so the behavior pin that used to live
# here (timeout -> exactly one `kill_process_group` call, `TimeoutError`
# still surfaces) and the end-to-end real-grandchild-reap pin both moved to
# the shared layer they now depend on:
#
# * behavior (non-raising timeout -> SubprocessTimeoutError, gh/git hardening
#   side effects): tests/test_subprocess_util.py::TestRunSubprocessResult
# * end-to-end (a REAL child that forks a grandchild is reaped
#   grandchild-and-all on `run_simple`'s own timeout): #9648 —
#   tests/regressions/test_hostrunner_reap_grandchildren.py
#
# `staging_bisect_loop._run_git` (the one surviving raw site) keeps its own
# bespoke reap path — pinned by `_HEAVY_SPAWN_SITES`/`_GROUP_REAP_SITES`
# above plus its dedicated cooperative-cancellation tests in
# tests/test_staging_bisect_loop.py.
