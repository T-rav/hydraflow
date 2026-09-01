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


def test_no_artifact_is_written_without_the_env_var(tmp_path: Path) -> None:
    """An ordinary run must not pay for an artifact nobody asked for."""
    sentinel = tmp_path / "unasked.json"
    _run_pytest(_TARGET, {})
    assert not sentinel.exists()


def test_the_artifact_records_real_call_durations(tmp_path: Path) -> None:
    out = tmp_path / "durs.json"
    result = _run_pytest(_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})
    assert result.returncode == 0, result.stdout[-2000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert _TARGET in data
    assert isinstance(data[_TARGET], float)


def test_a_second_run_merges_rather_than_clobbering(tmp_path: Path) -> None:
    """`make test` runs pytest twice. Overwriting would drop a whole lane's
    measurements and quietly halve the reading."""
    out = tmp_path / "durs.json"
    out.write_text(json.dumps({"tests/other_lane.py::test_x": 4.0}), encoding="utf-8")
    _run_pytest(_TARGET, {"HYDRAFLOW_DURATIONS_OUT": str(out)})
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "tests/other_lane.py::test_x" in data, "the earlier lane was clobbered"
    assert _TARGET in data
