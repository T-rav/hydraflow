"""MockWorld scenario for the persistent-error self-repair actuator (#10140).

Follow-up to #9854's read-only per-loop health harness
(``tests/scenarios/test_loop_health.py``) — this exercises the ACTUATOR half
end-to-end through ``HealthMonitorLoop._do_work`` (not the unit-level
``_check_persistent_worker_errors`` calls in
``tests/test_health_monitor_persistent_error_actuator.py``).

Seeds a worker heartbeat that reports ``error`` and drives
``HealthMonitorLoop`` through ``_ERROR_STREAK_THRESHOLD`` cycles of
``run_with_loops`` (same ``HealthMonitorLoop`` instance across the internal
cycles, so its in-memory streak counter accumulates):

* an UNKNOWN failing loop (``flake_tracker``) gets ONE deduped
  ``hydraflow-find`` + ``loop-persistent-error`` issue filed through the fake
  GitHub port;
* ``principles_audit`` (the KNOWN pattern) gets its 404'd ``managed_repos``
  entry auto-pruned (``enabled=False``) instead — no issue filed.

The known-repair probe (``git ls-remote``) is monkeypatched so this scenario
never touches the network.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from config import ManagedRepo
from health_monitor_loop import _ERROR_STREAK_THRESHOLD
from tests.helpers import make_bg_loop_deps
from tests.scenarios.catalog.loop_catalog import LoopCatalog
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _error_heartbeat() -> dict[str, object]:
    return {
        "status": "error",
        "last_run": _dt.datetime.now(_dt.UTC).isoformat(),
        "details": {},
    }


async def test_unknown_loop_persistent_error_files_one_issue(
    tmp_path, monkeypatch
) -> None:
    world = MockWorld(tmp_path)
    state = world._harness.state
    state.set_worker_heartbeat("flake_tracker", _error_heartbeat())

    await world.run_with_loops(["health_monitor"], cycles=_ERROR_STREAK_THRESHOLD)

    open_issues = [
        issue
        for issue in world.github._issues.values()
        if "loop-persistent-error" in issue.labels
    ]
    assert len(open_issues) == 1
    assert "flake_tracker" in open_issues[0].title

    # A further cycle (streak keeps growing) must not file a second issue.
    await world.run_with_loops(["health_monitor"], cycles=1)
    open_issues = [
        issue
        for issue in world.github._issues.values()
        if "loop-persistent-error" in issue.labels
    ]
    assert len(open_issues) == 1


async def test_principles_audit_404_repo_auto_pruned_no_issue(
    tmp_path, monkeypatch
) -> None:
    """``run_with_loops`` builds its own throwaway config per call (no seam
    for pre-seeding ``managed_repos``), so this drives the loop directly via
    ``LoopCatalog`` — the same builder registration ``run_with_loops`` uses
    internally — reusing MockWorld's fake GitHub port + a real StateTracker."""
    world = MockWorld(tmp_path)
    good = ManagedRepo(slug="good/repo")
    bad = ManagedRepo(slug="bad/repo")
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "managed_repos", [good, bad])

    state = world._harness.state
    state.set_worker_heartbeat("principles_audit", _error_heartbeat())

    loop = LoopCatalog.instantiate(
        "health_monitor",
        ports={"github": world.github, "state": state},
        config=bg.config,
        deps=bg.loop_deps,
    )

    # The git ls-remote probe is now an injected RepoProber seam (#10140);
    # inject a slug-aware fake (bad/repo 404s, everything else reachable)
    # instead of patching the moved run_subprocess_result — no network.
    class _SlugAwareProber:
        async def probe(self, slug: str) -> bool | None:
            return "bad/repo" not in slug

    loop._repo_prober = _SlugAwareProber()

    for _ in range(_ERROR_STREAK_THRESHOLD):
        await loop._do_work()

    enabled_by_slug = {mr.slug: mr.enabled for mr in bg.config.managed_repos}
    assert enabled_by_slug == {"good/repo": True, "bad/repo": False}

    persistent_error_issues = [
        issue
        for issue in world.github._issues.values()
        if "loop-persistent-error" in issue.labels
    ]
    assert persistent_error_issues == []
