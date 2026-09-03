"""A vanishing run directory must not cost the GC loop its whole tick.

#6717's unit pins call `get_storage_stats` and `purge_expired` directly. This
drives `RunsGCLoop` with a REAL `RunRecorder` over a real runs tree — the
existing L20 scenarios in test_caretaker_loops_part2.py use a MagicMock
recorder, so nothing exercised the walk itself — and asserts the tick
completes and reports figures.

That is the loop-level consequence: an unguarded `stat()` on a file the GC
had already removed raised out of `_do_work`, so the tick returned nothing,
the worker heartbeat went to error, and the storage numbers the operator
reads went stale — all because the collector was doing its job at the same
moment the stats walk was reading the same tree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _seed_runs(root: Path) -> Path:
    """One run old enough to purge, one recent enough to survive it.

    The victim has to be in the SURVIVING run. `purge_expired` runs before
    `get_storage_stats` in the loop's tick, so a victim inside an expired run
    is already deleted by the time the stats walk starts and the race never
    fires — the first version of this test seeded two old runs and its own
    guard caught that it was proving nothing.
    """
    expired = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y%m%dT%H%M%SZ")
    surviving = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for stamp in (expired, surviving):
        d = root / "42" / stamp
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.txt").write_bytes(b"x" * 100)
        (d / "transcript.txt").write_bytes(b"y" * 200)
    return root / "42" / surviving / "transcript.txt"


async def test_a_file_vanishing_mid_walk_does_not_end_the_tick(
    tmp_path, monkeypatch
) -> None:
    from run_recorder import RunRecorder  # noqa: PLC0415

    runs_root = tmp_path / "runs"
    vanishing = _seed_runs(runs_root)

    config = MagicMock()
    config.repo_data_path.return_value = runs_root
    recorder = RunRecorder(config)

    # Delete the file between `is_file()` and `stat()` — the exact race a
    # concurrent collector creates, and the one the unguarded walk died on.
    original_stat = Path.stat
    seen = {"n": 0}

    def stat_deleting_on_second_call(self_path: Path, *a, **kw):
        if self_path == vanishing:
            seen["n"] += 1
            if seen["n"] == 2 and vanishing.exists():
                vanishing.unlink()
        return original_stat(self_path, *a, **kw)

    monkeypatch.setattr(Path, "stat", stat_deleting_on_second_call)

    world = MockWorld(tmp_path)
    _seed_ports(world, run_recorder=recorder)

    stats = await world.run_with_loops(["runs_gc"], cycles=1)

    result = stats["runs_gc"]
    assert result is not None, (
        "the GC tick returned nothing — the stats walk raised on the file the "
        "collector removed, which is exactly what #6717 is about"
    )
    assert seen["n"] >= 2, (
        "the race never triggered, so this test proved nothing; the walk "
        f"stat()ed the victim {seen['n']} time(s)"
    )
    assert result.get("expired_purged", 0) >= 1, (
        f"the 90-day-old runs should still have been purged; got {result}"
    )
