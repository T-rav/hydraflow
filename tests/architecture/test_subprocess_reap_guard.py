"""Spawn-side reap guard (#9623) — the orphaned-grandchild defect class.

The reap family is behavioral-complete: ``process_group.kill_process_group``
is the single guarded primitive (#10017, location-gated by
``test_process_group_kill_guard.py``), ``HostRunner.run_simple`` and
``stream_claude_process`` reap their process group on timeout AND
cancellation (#9648/#9911), and ``tests/regressions/test_issue_9553.py``
pins the zero-orphan end-to-end story. What was still missing (#9623) is the
STRUCTURAL fence: a NEW spawn site with a dropped cancel handler — or a new
raw spawn that bypasses the reap-aware helpers entirely — was only caught
behaviorally, if its author happened to write the behavioral test.

Two ratchets, both shrink-only (mirroring
``test_sandbox_seam_completeness.py``):

1. **Raw-spawn containment** — a raw live-child spawn primitive
   (``create_subprocess_exec``/``_shell``, ``subprocess.Popen``,
   ``os.spawn*``) may appear only inside the sanctioned reap-aware
   implementations (``HostRunner.run_simple``,
   ``HostRunner.create_streaming_process``) or the grandfathered baseline.
   Everything else routes through ``subprocess_util.run_subprocess`` /
   ``run_subprocess_result`` (one-shot; bounded + registry-reaped) or
   ``runner_utils.stream_claude_process`` (streaming agents).
2. **Reap pairing** — every function spawning a session leader
   (``start_new_session=True``, or a ``create_streaming_process`` call not
   opting out) must call ``kill_process_group`` inside BOTH an
   ``except asyncio.CancelledError`` and an ``except TimeoutError`` handler.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.architecture.sandbox_seam_scan import ratchet_diff
from tests.architecture.subprocess_reap_scan import (
    scan_raw_spawn_signatures,
    scan_reap_scope,
    scan_reap_violations,
)

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

# The only two places in src/ allowed to call a raw spawn primitive: the
# SubprocessRunner host implementations that every sanctioned helper
# (run_subprocess / run_subprocess_result via _run_gated -> run_simple;
# stream_claude_process via create_streaming_process) funnels into. Both
# carry the reap machinery: process-group registry (#9911/#10019) and
# group-kill on timeout/cancel.
SANCTIONED_RAW_SPAWNERS: frozenset[str] = frozenset(
    {
        "src/execution.py::HostRunner.run_simple::create_subprocess_exec",
        "src/execution.py::HostRunner.create_streaming_process::create_subprocess_exec",
    }
)

# Raw spawn sites that predate this guard, keyed ``{signature: count}``
# (see subprocess_reap_scan.scan_raw_spawn_signatures). DO NOT ADD ENTRIES:
# a new spawn goes through run_subprocess / run_subprocess_result /
# stream_claude_process instead. Remove entries as sites migrate — the
# ratchet only shrinks.
#
# * dashboard_routes / preflight: interactive UI/boot one-shots (git/gh
#   plumbing) that predate the #9554/#10060 migration wave.
# * subprocess_util.probe_auth_availability: the fail-open `gh auth status`
#   probe; cannot route through _run_gated without recursing into the very
#   machinery it corroborates.
GRANDFATHERED_RAW_SPAWN_BASELINE: dict[str, int] = {
    "src/dashboard_routes/_onboarding_routes.py::_run_checked::create_subprocess_exec": 1,
    "src/dashboard_routes/_routes.py::_run_dialog_command::create_subprocess_exec": 1,
    "src/dashboard_routes/_state_routes.py::register._detect_repo_slug_from_path::create_subprocess_exec": 1,
    "src/dashboard_routes/_state_routes.py::register.add_repo_by_path::create_subprocess_exec": 1,
    "src/dashboard_routes/_state_routes.py::register.clone_github_repo::create_subprocess_exec": 1,
    "src/dashboard_routes/_state_routes.py::register.list_github_repos::create_subprocess_exec": 1,
    "src/preflight/__init__.py::_check_gh_auth::create_subprocess_exec": 1,
    "src/subprocess_util.py::probe_auth_availability::create_subprocess_exec": 1,
}

# Session-leader spawn sites that do not reap via except-handlers, keyed
# ``relpath::qualname``. DO NOT ADD ENTRIES; prune when the site conforms.
#
# Empty: staging_bisect_loop._run_git migrated to the shared runner
# (get_default_runner().run_simple, #9577) — it no longer spawns a
# session-leader directly, so the whole-group reap now lives inside
# HostRunner.run_simple rather than in this loop.
GRANDFATHERED_REAP_BASELINE: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Live-tree ratchets
# ---------------------------------------------------------------------------


def test_scan_finds_the_sanctioned_spawn_implementations() -> None:
    """Anti-vacuity canary for the containment scan.

    If the scan scope or primitive set regresses (rename, glob typo), the
    containment assertions pass vacuously on an empty scan. The two
    sanctioned HostRunner sites exist as long as HydraFlow spawns anything.
    """
    current = scan_raw_spawn_signatures(REPO_ROOT)
    missing = SANCTIONED_RAW_SPAWNERS - set(current)
    assert not missing, (
        f"Sanctioned spawn implementations not seen by the scan: {sorted(missing)}. "
        "Either the scanner scope regressed or the HostRunner spawn sites "
        "moved — update SANCTIONED_RAW_SPAWNERS in the same change."
    )


def test_no_new_raw_spawn_sites_outside_reap_aware_helpers() -> None:
    current = scan_raw_spawn_signatures(REPO_ROOT)
    unsanctioned = {
        signature: count
        for signature, count in current.items()
        if signature not in SANCTIONED_RAW_SPAWNERS
    }
    new, _resolved = ratchet_diff(unsanctioned, GRANDFATHERED_RAW_SPAWN_BASELINE)
    assert not new, (
        f"Raw subprocess spawn sites outside the reap-aware helpers: {new}. "
        "A raw spawn bypasses reap-on-cancel/timeout and the process-group "
        "registry — its children orphan on cancellation (#9623, the "
        "#9648/#9553 defect class). Route one-shot commands through "
        "subprocess_util.run_subprocess / run_subprocess_result and "
        "streaming agent spawns through runner_utils.stream_claude_process. "
        "Do NOT grow GRANDFATHERED_RAW_SPAWN_BASELINE — the ratchet only "
        "shrinks."
    )


def test_raw_spawn_baseline_only_shrinks() -> None:
    current = scan_raw_spawn_signatures(REPO_ROOT)
    unsanctioned = {
        signature: count
        for signature, count in current.items()
        if signature not in SANCTIONED_RAW_SPAWNERS
    }
    _new, resolved = ratchet_diff(unsanctioned, GRANDFATHERED_RAW_SPAWN_BASELINE)
    assert not resolved, (
        f"Baseline lists raw spawn sites no longer present: {resolved}. "
        "Prune them from GRANDFATHERED_RAW_SPAWN_BASELINE in this change so "
        "the baseline stays honest."
    )


def test_reap_scan_sees_the_load_bearing_spawn_paths() -> None:
    """Anti-vacuity canary for the reap-pairing scan."""
    in_scope = scan_reap_scope(REPO_ROOT)
    assert "src/execution.py::HostRunner.run_simple" in in_scope
    assert "src/runner_utils.py::stream_claude_process" in in_scope


def test_session_leader_spawns_reap_in_both_cancel_and_timeout_handlers() -> None:
    violations = scan_reap_violations(REPO_ROOT)
    new = {
        signature: deficit
        for signature, deficit in violations.items()
        if signature not in GRANDFATHERED_REAP_BASELINE
    }
    assert not new, (
        f"Session-leader spawn sites missing reap handlers: {new}. A process "
        "spawned with start_new_session=True is its own group leader; only "
        "process_group.kill_process_group reaps its whole tree, and it must "
        "be called from BOTH an `except asyncio.CancelledError` and an "
        "`except TimeoutError` handler — a bare proc.kill() (or a dropped "
        "handler) silently orphans grandchildren (#9623, #9648). Do NOT grow "
        "GRANDFATHERED_REAP_BASELINE — the ratchet only shrinks."
    )


def test_reap_baseline_only_shrinks() -> None:
    violations = scan_reap_violations(REPO_ROOT)
    stale = GRANDFATHERED_REAP_BASELINE - set(violations)
    assert not stale, (
        f"Baseline lists reap sites that now conform or no longer spawn: "
        f"{sorted(stale)}. Prune them from GRANDFATHERED_REAP_BASELINE in "
        "this change so the baseline stays honest."
    )


def test_reap_baseline_entries_are_not_raw_spawn_sanctioned() -> None:
    """The two allowlists must stay disjoint.

    A site cannot be both a sanctioned reap-aware implementation and a
    grandfathered reap violation — that would grant it a permanent pass.
    """
    sanctioned_functions = {
        signature.rsplit("::", 1)[0] for signature in SANCTIONED_RAW_SPAWNERS
    }
    conflicted = GRANDFATHERED_REAP_BASELINE & sanctioned_functions
    assert not conflicted, (
        f"Sites in both SANCTIONED_RAW_SPAWNERS and "
        f"GRANDFATHERED_REAP_BASELINE: {sorted(conflicted)}."
    )


# ---------------------------------------------------------------------------
# Scanner unit tests against inline fixtures
# ---------------------------------------------------------------------------


class TestRawSpawnScanner:
    """Containment-scan mechanics on synthetic trees."""

    def test_flags_raw_spawn_primitives(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/rogue.py": """
                    import asyncio
                    import os
                    import subprocess


                    async def exec_site() -> None:
                        await asyncio.create_subprocess_exec("git", "status")


                    def popen_site() -> None:
                        subprocess.Popen(["ls"])


                    def spawn_site() -> None:
                        os.spawnv(os.P_NOWAIT, "/bin/ls", ["ls"])
                    """,
            }
        )
        assert scan_raw_spawn_signatures(root) == {
            "src/rogue.py::exec_site::create_subprocess_exec": 1,
            "src/rogue.py::popen_site::Popen": 1,
            "src/rogue.py::spawn_site::spawnv": 1,
        }

    def test_sanctioned_helper_calls_are_not_raw_spawns(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/clean.py": """
                    async def helper_users(runner) -> None:
                        await run_subprocess("gh", "pr", "view")
                        await run_subprocess_result("git", "status")
                        await stream_claude_process(cmd=["claude", "-p"], prompt="hi")
                        await runner.run_simple(["git", "status"])
                    """,
            }
        )
        assert scan_raw_spawn_signatures(root) == {}

    def test_counts_pin_multiplicity_per_function(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/twice.py": """
                    import asyncio


                    async def double_spawn() -> None:
                        await asyncio.create_subprocess_exec("a")
                        await asyncio.create_subprocess_exec("b")
                    """,
            }
        )
        signature = "src/twice.py::double_spawn::create_subprocess_exec"
        current = scan_raw_spawn_signatures(root)
        assert current[signature] == 2
        new, _resolved = ratchet_diff(current, {signature: 1})
        assert new == {signature: 1}


_CONFORMING_SPAWN = """
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
            kill_process_group(proc)
            with contextlib.suppress(ProcessLookupError, OSError):
                await proc.wait()
            raise
        except asyncio.CancelledError:
            kill_process_group(proc)
            raise
    """


class TestReapPairingScanner:
    """Reap-pairing mechanics on synthetic trees."""

    def test_conforming_site_is_in_scope_and_clean(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree({"src/agent.py": _CONFORMING_SPAWN})
        assert scan_reap_scope(root) == {
            "src/agent.py::run_agent": ["create_subprocess_exec"]
        }
        assert scan_reap_violations(root) == {}

    def test_bare_proc_kill_in_handlers_is_a_violation(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
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
            }
        )
        violations = scan_reap_violations(root)
        assert set(violations) == {"src/agent.py::run_agent"}
        assert "CancelledError" in violations["src/agent.py::run_agent"]
        assert "TimeoutError" in violations["src/agent.py::run_agent"]

    def test_dropped_cancel_handler_is_a_violation(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/agent.py": """
                    import asyncio

                    from process_group import kill_process_group


                    async def run_agent(cmd: list[str]) -> None:
                        proc = await asyncio.create_subprocess_exec(
                            *cmd, start_new_session=True
                        )
                        try:
                            await asyncio.wait_for(proc.communicate(), timeout=5.0)
                        except TimeoutError:
                            kill_process_group(proc)
                            raise
                    """,
            }
        )
        violations = scan_reap_violations(root)
        assert set(violations) == {"src/agent.py::run_agent"}
        assert "CancelledError" in violations["src/agent.py::run_agent"]
        assert "TimeoutError" not in violations["src/agent.py::run_agent"]

    def test_module_local_reaper_wrapper_conforms(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/agent.py": """
                    import asyncio

                    from process_group import kill_process_group


                    def _reap(proc) -> None:
                        kill_process_group(proc)


                    async def run_agent(cmd: list[str]) -> None:
                        proc = await asyncio.create_subprocess_exec(
                            *cmd, start_new_session=True
                        )
                        try:
                            await asyncio.wait_for(proc.communicate(), timeout=5.0)
                        except TimeoutError:
                            _reap(proc)
                            raise
                        except asyncio.CancelledError:
                            _reap(proc)
                            raise
                    """,
            }
        )
        assert scan_reap_violations(root) == {}

    def test_tuple_handler_counts_for_timeout(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/agent.py": """
                    import asyncio

                    from process_group import kill_process_group


                    async def run_agent(cmd: list[str]) -> None:
                        proc = await asyncio.create_subprocess_exec(
                            *cmd, start_new_session=True
                        )
                        try:
                            await asyncio.wait_for(proc.communicate(), timeout=5.0)
                        except (TimeoutError, OSError):
                            kill_process_group(proc)
                            raise
                        except asyncio.CancelledError:
                            kill_process_group(proc)
                            raise
                    """,
            }
        )
        assert scan_reap_violations(root) == {}

    def test_non_session_leader_spawns_are_out_of_scope(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        """No literal True keyword -> out of reap scope (containment still
        fences the raw site). Covers the HostRunner.create_streaming_process
        factory, which threads start_new_session as a variable."""
        root = fixture_src_tree(
            {
                "src/agent.py": """
                    import asyncio


                    async def no_keyword(cmd: list[str]) -> None:
                        await asyncio.create_subprocess_exec(*cmd)


                    async def literal_false(cmd: list[str]) -> None:
                        await asyncio.create_subprocess_exec(
                            *cmd, start_new_session=False
                        )


                    async def variable_threaded(cmd, start_new_session: bool) -> None:
                        await asyncio.create_subprocess_exec(
                            *cmd, start_new_session=start_new_session
                        )
                    """,
            }
        )
        assert scan_reap_scope(root) == {}
        assert scan_reap_violations(root) == {}

    def test_streaming_factory_calls_are_in_scope_unless_opted_out(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        root = fixture_src_tree(
            {
                "src/streamer.py": """
                    import asyncio


                    async def defaulted(runner) -> None:
                        await runner.create_streaming_process(["claude", "-p"])


                    async def opted_out(runner) -> None:
                        await runner.create_streaming_process(
                            ["claude", "-p"], start_new_session=False
                        )
                    """,
            }
        )
        scope = scan_reap_scope(root)
        assert set(scope) == {"src/streamer.py::defaulted"}
        violations = scan_reap_violations(root)
        assert set(violations) == {"src/streamer.py::defaulted"}

    def test_nested_function_spawns_attribute_to_the_nested_scope(
        self, fixture_src_tree: Callable[[dict[str, str]], Path]
    ) -> None:
        """A parent with conforming handlers cannot launder a nested def's
        spawn — the nested function owns (and lacks) its own handlers."""
        root = fixture_src_tree(
            {
                "src/nested.py": """
                    import asyncio

                    from process_group import kill_process_group


                    async def outer(cmd: list[str]) -> None:
                        async def inner() -> None:
                            await asyncio.create_subprocess_exec(
                                *cmd, start_new_session=True
                            )

                        try:
                            await inner()
                        except TimeoutError:
                            kill_process_group(None)
                            raise
                        except asyncio.CancelledError:
                            kill_process_group(None)
                            raise
                    """,
            }
        )
        assert set(scan_reap_violations(root)) == {"src/nested.py::outer.inner"}
