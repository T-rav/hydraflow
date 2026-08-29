"""The spin watchdog must actually fire, and must name the wedged test.

A watchdog that never fires is indistinguishable from a healthy suite, which
is the precise failure mode `tests/hf_spin_watch.py` exists to end. So this
does not inspect the plugin's internals — it runs a genuinely non-terminating
test in a subprocess and asserts the dump names it and points at the line.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_WEDGED_TEST = """
def _inner_spin():
    i = 0
    while True:
        i += 1


def test_a_wedged_pure_python_loop():
    _inner_spin()
"""


def _run_wedged(tmp_path: Path, budget: str) -> list[Path]:
    target = tmp_path / "test_wedged_probe.py"
    target.write_text(_WEDGED_TEST, encoding="utf-8")
    out_prefix = tmp_path / "spin"
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-p",
            "tests.hf_spin_watch",
            "-q",
            "-p",
            "no:randomly",
            "--timeout=15",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # the probe is EXPECTED to fail; the dump is the subject
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT}",
            "HF_SPIN_TIMEOUT": budget,
            "HF_SPIN_OUT": str(out_prefix),
            "HOME": str(tmp_path),
        },
    )
    return sorted(tmp_path.glob("spin-*.txt"))


@pytest.mark.timeout(180)
def test_the_watchdog_names_the_wedged_test_and_its_line(tmp_path: Path) -> None:
    dumps = _run_wedged(tmp_path, budget="2")
    assert dumps, (
        "the watchdog produced no dump for a test that never returns — it is "
        "inert, which is the exact condition it exists to detect"
    )
    text = dumps[0].read_text(encoding="utf-8")
    assert "test_wedged_probe.py::test_a_wedged_pure_python_loop" in text, (
        f"dump does not name the wedged test:\n{text[:800]}"
    )
    assert "_inner_spin" in text, (
        f"dump does not reach the spinning frame:\n{text[:800]}"
    )


@pytest.mark.timeout(180)
def test_it_redumps_on_each_doubling_so_slow_is_not_wedged(tmp_path: Path) -> None:
    """One dump means slow; repeated dumps mean non-terminating."""
    dumps = _run_wedged(tmp_path, budget="2")
    assert dumps
    text = dumps[0].read_text(encoding="utf-8")
    assert text.count("hf-spin-watch") >= 2, (
        "expected repeated dumps on the doubling schedule, which is what "
        f"distinguishes a slow test from a wedged one; got:\n{text[:400]}"
    )


_TWO_TESTS = """
def test_fast_one():
    assert True


def test_wedged():
    i = 0
    while True:
        i += 1
"""


@pytest.mark.timeout(240)
def test_it_stays_silent_about_idle_processes(tmp_path: Path) -> None:
    """Regression: it reported the xdist controller and an idle worker.

    On its first live run the watchdog dumped twice against
    `<session: import/collect>` — pid was the xdist CONTROLLER, which never
    executes tests, so its nodeid never advanced. Guarding the controller
    alone was not enough: with `--dist loadscope` a worker given no work sits
    at the same sentinel and reports itself too.

    An instrument that cries wolf gets ignored, which would cost more than
    the hang it was built to find. It must speak only while a test runs.
    """
    target = tmp_path / "test_two_probe.py"
    target.write_text(_TWO_TESTS, encoding="utf-8")
    out_prefix = tmp_path / "spin"
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-p",
            "tests.hf_spin_watch",
            "-n",
            "2",
            "--dist",
            "loadscope",
            "-q",
            "-p",
            "no:randomly",
            "--timeout=20",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT}",
            "HF_SPIN_TIMEOUT": "3",
            "HF_SPIN_OUT": str(out_prefix),
            "HOME": str(tmp_path),
        },
    )
    dumps = sorted(tmp_path.glob("spin-*.txt"))
    assert dumps, "the wedged test produced no dump at all"

    blob = "\n".join(d.read_text(encoding="utf-8") for d in dumps)
    assert "test_wedged" in blob, f"the wedged test was not named:\n{blob[:400]}"
    assert "session: import/collect" not in blob, (
        "the watchdog dumped a process that was not running a test — the "
        f"controller/idle-worker false positive is back:\n{blob[:600]}"
    )
    assert "between tests" not in blob, (
        f"the watchdog dumped between tests rather than during one:\n{blob[:600]}"
    )
