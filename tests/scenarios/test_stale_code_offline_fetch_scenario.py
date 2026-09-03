"""An unreachable origin must not alert, and must not wedge the tick.

`_check_stale_code` is the one spawn in `health_monitor_loop` that no config
flag turns off, so on the air-gapped sandbox network it RUNS. #12105 gave that
its own seam kind (`bounded_offline_failure`) on the strength of two lines of
source: an explicit `timeout=` on the fetch, and an `except RuntimeError` that
covers `SubprocessTimeoutError`.

Reading those lines is not the same as watching the loop survive. This drives
the real `HealthMonitorLoop` with a `git fetch` that fails the way an
air-gapped network fails, and asserts the consequences that matter: no
`factory-stale-code` issue is filed, and the tick completes.

Filing on a failed fetch would be the actual harm — `get_commits_behind` reads
LOCAL tracking refs, so a fetch that never landed leaves a ref that can be
arbitrarily old, and alerting off it means a `factory-stale-code` issue whose
commits-behind count is fiction.

The reachable-origin case is the decoy. Without it, "no issue filed" would
pass just as well against a loop that never files at all, or one whose
`_check_stale_code` is never reached from `_heavy`.
"""

from __future__ import annotations

import pytest

from subprocess_util import SubprocessTimeoutError
from tests.helpers import make_bg_loop_deps
from tests.scenarios.catalog.loop_catalog import LoopCatalog
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_STALE_LABEL = "factory-stale-code"


def _build_loop(world: MockWorld, tmp_path):
    bg = make_bg_loop_deps(tmp_path)
    loop = LoopCatalog.instantiate(
        "health_monitor",
        ports={"github": world.github, "state": world._harness.state},
        config=bg.config,
        deps=bg.loop_deps,
    )
    return loop, bg.config


async def test_an_unreachable_origin_files_no_stale_code_alert(
    tmp_path, monkeypatch
) -> None:
    """The air-gapped shape: the fetch times out inside its own tier."""
    import health_monitor_loop._freshness as freshness

    world = MockWorld(tmp_path)
    loop, _config = _build_loop(world, tmp_path)

    fetches: list[tuple[str, ...]] = []

    async def _offline(*argv: str, **_kw: object) -> None:
        fetches.append(argv)
        raise SubprocessTimeoutError("git fetch timed out after 30.0s")

    monkeypatch.setattr(freshness, "run_subprocess", _offline)
    # A commits-behind reading far past the threshold — so if the loop ever
    # got past the failed fetch, it would certainly file.
    monkeypatch.setattr(freshness, "get_commits_behind", lambda **_k: 9999)

    await loop._check_stale_code()

    assert fetches, "the fetch never ran — this scenario asserts nothing"
    titles = [i.title for i in world.github._issues.values()]
    assert not [t for t in titles if "stale" in t.lower()], (
        "alerted on a local tracking ref the failed fetch never refreshed"
    )


async def test_a_reachable_origin_still_files_when_genuinely_stale(
    tmp_path, monkeypatch
) -> None:
    """The decoy: prove the loop files at all, and that _check_stale_code runs.

    Without this, the assertion above passes against a loop whose stale-code
    check is unreachable, or which never files anything.
    """
    import health_monitor_loop._freshness as freshness

    world = MockWorld(tmp_path)
    loop, config = _build_loop(world, tmp_path)

    async def _online(*_argv: str, **_kw: object) -> None:
        return None

    monkeypatch.setattr(freshness, "run_subprocess", _online)
    monkeypatch.setattr(
        freshness,
        "get_commits_behind",
        lambda **_k: config.stale_code_alert_threshold + 1,
    )

    await loop._check_stale_code()

    labels = [lbl for i in world.github._issues.values() for lbl in i.labels]
    assert _STALE_LABEL in labels, (
        "the loop filed nothing even with a reachable origin and a stale ref — "
        "the offline assertion above would then be vacuous"
    )
