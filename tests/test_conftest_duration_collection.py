"""The duration artifact conftest writes for the slowness sensor (#11910).

The sensor is pure over ``{nodeid: seconds}``, and something has to produce
that mapping. Duration is the one erosion reading that cannot be derived from
source, so unlike mass and suite-hygiene it needs a real measurement handed in.

These pin the collector's contract, which is easy to get subtly wrong: it must
be off by default, must survive an unwritable path, and must MERGE rather than
overwrite — ``make test`` invokes pytest twice (parallel bulk, then the serial
paths) and a clobbering writer would silently discard a whole lane.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _run_pytest(target: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "PYTHONPATH": f"{_REPO / 'src'}:{_REPO}", **env_extra}
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "-p", "no:randomly"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


_TARGET = "tests/test_erosion_slowness.py::TestCompute::test_share_is_the_concentration_not_the_count"
_OTHER_TARGET = (
    "tests/test_erosion_slowness.py::TestCompute::test_the_roster_is_slowest_first"
)


def test_no_artifact_is_written_without_the_env_var(tmp_path: Path) -> None:
    """An ordinary run must not pay for an artifact nobody asked for."""
    sentinel = tmp_path / "unasked.json"
    _run_pytest(_TARGET, {})
    assert not sentinel.exists()


def test_the_artifact_records_real_call_durations(tmp_path: Path) -> None:
    out = tmp_path / "durs.json"
    result = _run_pytest(_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})
    assert result.returncode == 0, result.stdout[-2000:]
    shards = sorted(tmp_path.glob("durs.*.json"))
    assert shards, "no shard written"
    data = json.loads(shards[0].read_text(encoding="utf-8"))
    assert _TARGET in data
    assert isinstance(data[_TARGET], float)


def test_concurrent_lanes_each_get_their_own_shard(tmp_path: Path) -> None:
    """`make quality` runs four pytest lanes CONCURRENTLY.

    A writer that read-modify-wrote one shared file would interleave between
    them and drop whole lanes — a lost update that presents as a smaller,
    cleaner-looking suite. One shard per process makes that impossible.
    """
    out = tmp_path / "durs.json"
    _run_pytest(_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})
    _run_pytest(_OTHER_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})

    shards = sorted(tmp_path.glob("durs.*.json"))
    assert len(shards) == 2, f"expected one shard per process, got {shards}"


def test_the_reader_merges_every_shard_into_one_reading(tmp_path: Path) -> None:
    """The other half: sharded writes are only correct if the read reassembles
    them. A reader that took one shard would report a fraction of the suite."""
    import sys as _sys

    _sys.path.insert(0, str(_REPO / "src"))
    from erosion.slowness import collect_durations

    out = tmp_path / "durs.json"
    _run_pytest(_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})
    _run_pytest(_OTHER_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})

    merged = collect_durations(out)
    assert _TARGET in merged
    assert _OTHER_TARGET in merged
