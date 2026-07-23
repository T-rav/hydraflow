"""Regression: a spawn site that drops its reap-on-cancel handler is red.

Issue #9623: the reap family (kill_process_group #10017, run_simple /
stream_claude_process group-reap #9648/#9911, the zero-orphan e2e pin
#9553) enforced reap-on-cancel only BEHAVIORALLY — a new spawn site with a
dropped ``except asyncio.CancelledError`` handler, or a raw
``create_subprocess_exec`` bypassing the reap-aware helpers entirely,
shipped silently unless its author wrote the behavioral test. This pins the
spawn-side scanner mechanics on synthetic trees: the exact
dropped-cancel-handler and rogue-raw-spawn shapes must stay red, and the
conforming shape (including the module-local wrapper aliases the live tree
uses, ``execution._reap_process_group`` / ``runner_utils._kill_proc_group``)
must stay green. If any of these regress, the guard in
``tests/architecture/test_subprocess_reap_guard.py`` goes vacuously green
and the next orphaned-grandchild regression ships without a red CI signal.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from tests.architecture.sandbox_seam_scan import ratchet_diff
from tests.architecture.subprocess_reap_scan import (
    scan_raw_spawn_signatures,
    scan_reap_scope,
    scan_reap_violations,
)

_CONFORMING = """
    import asyncio
    import contextlib

    from process_group import kill_process_group


    async def run_agent(cmd: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd, start_new_session=True
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, OSError):
                kill_process_group(proc)
                await proc.wait()
            raise
        except asyncio.CancelledError:
            kill_process_group(proc)
            raise
    """

# The same site after the exact regression #9623 fears: the cancel handler
# is gone (timeout still reaps), so a watchdog-cancelled cycle orphans the
# whole grandchild tree.
_DROPPED_CANCEL = """
    import asyncio
    import contextlib

    from process_group import kill_process_group


    async def run_agent(cmd: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd, start_new_session=True
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, OSError):
                kill_process_group(proc)
                await proc.wait()
            raise
    """


def _write_tree(root: Path, spec: dict[str, str]) -> None:
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(body).lstrip("\n"))


def test_conforming_spawn_site_stays_green(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"src/agent.py": _CONFORMING})
    assert scan_reap_scope(tmp_path) == {
        "src/agent.py::run_agent": ["create_subprocess_exec"]
    }
    assert scan_reap_violations(tmp_path) == {}


def test_dropped_cancel_handler_reddens(tmp_path: Path) -> None:
    """The canonical #9623 regression: cancel handler deleted, timeout kept."""
    _write_tree(tmp_path, {"src/agent.py": _DROPPED_CANCEL})
    violations = scan_reap_violations(tmp_path)
    assert set(violations) == {"src/agent.py::run_agent"}
    assert "CancelledError" in violations["src/agent.py::run_agent"]
    assert "TimeoutError" not in violations["src/agent.py::run_agent"]


def test_wrapper_alias_reap_stays_green(tmp_path: Path) -> None:
    """The live tree reaps via one-hop wrappers; scanner must honor them.

    If alias resolution regresses, run_simple / stream_claude_process would
    flag as violations (loud), but this pins the mechanic so a scanner
    refactor cannot quietly change what "conforming" means.
    """
    _write_tree(
        tmp_path,
        {
            "src/agent.py": """
                import asyncio

                from process_group import kill_process_group


                def _reap_process_group(proc) -> None:
                    kill_process_group(proc)


                async def run_agent(cmd: list[str]) -> None:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, start_new_session=True
                    )
                    try:
                        await asyncio.wait_for(proc.communicate(), timeout=5.0)
                    except TimeoutError:
                        _reap_process_group(proc)
                        raise
                    except asyncio.CancelledError:
                        _reap_process_group(proc)
                        raise
                """,
        },
    )
    assert scan_reap_violations(tmp_path) == {}


def test_bare_proc_kill_never_counts_as_a_reap(tmp_path: Path) -> None:
    """proc.kill() reaps the leader only — grandchildren survive (#9648)."""
    _write_tree(
        tmp_path,
        {
            "src/agent.py": """
                import asyncio


                async def run_agent(cmd: list[str]) -> None:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, start_new_session=True
                    )
                    try:
                        await asyncio.wait_for(proc.communicate(), timeout=5.0)
                    except TimeoutError:
                        proc.kill()
                        raise
                    except asyncio.CancelledError:
                        proc.kill()
                        raise
                """,
        },
    )
    violations = scan_reap_violations(tmp_path)
    assert set(violations) == {"src/agent.py::run_agent"}


def test_new_raw_spawn_site_reddens_the_containment_ratchet(
    tmp_path: Path,
) -> None:
    """A rogue Popen/create_subprocess_exec outside the helpers is flagged."""
    _write_tree(
        tmp_path,
        {
            "src/rogue_loop.py": """
                import subprocess


                def shell_out() -> None:
                    subprocess.Popen(["make", "quality"])
                """,
        },
    )
    current = scan_raw_spawn_signatures(tmp_path)
    new, resolved = ratchet_diff(current, {})
    assert new == {"src/rogue_loop.py::shell_out::Popen": 1}
    assert not resolved


def test_migrated_raw_spawn_demands_baseline_prune(tmp_path: Path) -> None:
    """The ratchet only shrinks: a stale baseline entry must fail loudly."""
    _write_tree(
        tmp_path,
        {
            "src/clean.py": """
                async def helper_user() -> str:
                    return await run_subprocess("git", "status")
                """,
        },
    )
    current = scan_raw_spawn_signatures(tmp_path)
    stale_baseline = {"src/clean.py::helper_user::create_subprocess_exec": 1}
    new, resolved = ratchet_diff(current, stale_baseline)
    assert not new
    assert resolved == stale_baseline
