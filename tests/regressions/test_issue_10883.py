"""Regression: `Coverage (trailing)` must never run single-threaded again (#10883).

The lane ran 23,011 tests single-threaded (``-p no:xdist``) against a 30-minute
timeout and got CANCELLED on most pushes — pytest progress advanced steadily
to 81% at the instant of cancellation (no stall), so this was capacity
exhaustion, not a hang. ``GateHealthLoop`` misread the cancellation-at-timeout
signature as a `suspected_hang` and filed a killpg/mocked-`.pid` playbook
issue per push (#10390, #10391, #10393, #10883) — the wrong diagnosis, since
PR #10410 already hardened ``is_real_pid`` and the timeouts continued
unchanged.

The fix: mirror the `test` job's parallel + serial split so the coverage lane
fits its budget, and add ``--timeout`` so a *genuine* hang becomes a named
FAILED test instead of a silent job cancellation. These tests pin that shape
directly against the parsed workflow so it cannot silently regress back to a
single ``-p no:xdist`` step.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _ci_doc() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )


def _steps(job: str) -> list[dict]:
    return _ci_doc()["jobs"][job]["steps"]


def _run_lines(job: str) -> list[str]:
    return [str(step["run"]) for step in _steps(job) if "run" in step]


def _pytest_run_lines(job: str) -> list[str]:
    return [run for run in _run_lines(job) if "pytest" in run]


def test_coverage_job_never_runs_single_threaded() -> None:
    runs = _run_lines("coverage")
    assert not any("-p no:xdist" in run for run in runs), (
        "the coverage job must not run with -p no:xdist — that exact "
        "configuration is what timed out and got CANCELLED (#10883)"
    )


def test_coverage_job_has_a_parallel_leg() -> None:
    runs = _pytest_run_lines("coverage")
    assert any("-n auto" in run for run in runs), (
        "coverage job must parallelize its bulk under xdist, mirroring the "
        "`test` job, or it cannot fit its time budget"
    )


def test_coverage_job_timeout_minutes_raised_above_thirty() -> None:
    minutes = _ci_doc()["jobs"]["coverage"]["timeout-minutes"]
    assert minutes > 30, (
        "raise timeout-minutes for headroom now that the lane's own "
        "pytest invocations self-report real hangs via --timeout"
    )


def test_coverage_pytest_invocations_pass_per_test_timeout() -> None:
    runs = _pytest_run_lines("coverage")
    assert runs, "expected at least one pytest invocation in the coverage job"
    for run in runs:
        assert "--timeout=" in run, (
            f"pytest invocation missing --timeout — a real hang would go "
            f"back to a silent job cancellation instead of a named FAILED "
            f"test: {run!r}"
        )


def test_coverage_ignore_list_matches_test_job_parallel_leg() -> None:
    # Drift guard (pre-mortem risk 3): the xdist-unsafe ignore list now lives
    # in three places (test job, coverage job, Makefile PYTEST_SERIAL_PATHS).
    # The coverage job's parallel leg must ignore exactly what the `test`
    # job's parallel leg ignores — no separately-maintained fourth list.
    coverage_parallel = next(
        run for run in _pytest_run_lines("coverage") if "-n auto" in run
    )
    test_parallel = next(run for run in _pytest_run_lines("test") if "-n auto" in run)

    coverage_ignores = set(re.findall(r"--ignore=(\S+)", coverage_parallel))
    test_ignores = set(re.findall(r"--ignore=(\S+)", test_parallel))
    assert coverage_ignores == test_ignores


def test_exactly_one_coverage_leg_enforces_the_real_floor() -> None:
    runs = _pytest_run_lines("coverage")
    fail_unders = [
        match.group(1)
        for run in runs
        if (match := re.search(r"--cov-fail-under=(\d+)", run))
    ]
    nonzero = [v for v in fail_unders if v != "0"]

    assert len(nonzero) == 1, (
        "exactly one coverage leg must enforce the real --cov-fail-under "
        "floor — the other leg(s) carry partial worker data and must pass "
        "--cov-fail-under=0 so partial data never fails the floor"
    )
    # The real floor belongs on the terminal (last) pytest step: it is the
    # one that has seen every worker's appended coverage data.
    assert f"--cov-fail-under={nonzero[0]}" in runs[-1]


def test_coverage_job_still_excluded_from_ci_gate() -> None:
    # The coverage job is a trailing floor gate, not a merge blocker — this
    # work restores it, it must not become a required check.
    assert "coverage" not in _ci_doc()["jobs"]["ci-gate"]["needs"]


def test_coverage_job_both_legs_pass_cov_append() -> None:
    # Pre-mortem risk 1 (plan): if either leg drops --cov-append, that leg's
    # coverage data is never combined with the other's — --cov-fail-under=70
    # would then silently pass against a partial total instead of the real
    # one, hiding coverage loss instead of failing loud.
    runs = _pytest_run_lines("coverage")
    assert len(runs) == 2
    for run in runs:
        assert "--cov-append" in run, (
            f"pytest invocation is missing --cov-append — the other leg's "
            f"coverage data would be silently dropped: {run!r}"
        )


def _makefile_text() -> str:
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def _make_target_body(name: str) -> str:
    text = _makefile_text()
    match = re.search(rf"^{re.escape(name)}:.*?\n(?:\t.*\n?)*", text, re.MULTILINE)
    assert match is not None, f"no `{name}:` target found in Makefile"
    return match.group(0)


def test_makefile_coverage_target_never_runs_single_threaded() -> None:
    assert "-p no:xdist" not in _make_target_body("coverage")


def test_makefile_test_cov_target_never_runs_single_threaded() -> None:
    assert "-p no:xdist" not in _make_target_body("test-cov")


def test_makefile_coverage_target_reuses_shared_serial_vars() -> None:
    # Pre-mortem risk 3: the xdist-unsafe path list must not grow a fourth,
    # separately-maintained copy — `coverage` reuses the same
    # PYTEST_SERIAL_PATHS/PYTEST_PARALLEL vars `test` already uses.
    body = _make_target_body("coverage")
    assert "$(PYTEST_PARALLEL)" in body
    assert "$(PYTEST_SERIAL_PATHS)" in body


def test_makefile_coverage_target_both_legs_pass_cov_append() -> None:
    # Pre-mortem risk 1 (plan): same silent-coverage-loss guard as the ci.yml
    # coverage job, pinned locally too so `make coverage` cannot drift from CI.
    body = _make_target_body("coverage")
    assert body.count("--cov-append") == 2


def test_makefile_test_cov_target_both_legs_pass_cov_append() -> None:
    body = _make_target_body("test-cov")
    assert body.count("--cov-append") == 2


def _makefile_serial_paths() -> set[str]:
    """Expand `PYTEST_SERIAL_PATHS ?= <files> $(REAP_TESTS)` to literal paths."""
    text = _makefile_text()
    reap = re.search(r"REAP_TESTS\s*:=\s*(.*?)(?<!\\)\n", text, re.S)
    assert reap, "Could not locate `REAP_TESTS :=` in the Makefile"
    serial = re.search(r"PYTEST_SERIAL_PATHS\s*\?=\s*(.*?)(?<!\\)\n", text, re.S)
    assert serial, "Could not locate `PYTEST_SERIAL_PATHS ?=` in the Makefile"
    expanded = serial.group(1).replace("$(REAP_TESTS)", reap.group(1))
    return {tok for tok in expanded.replace("\\", " ").split() if tok}


def test_coverage_serial_leg_covers_every_makefile_serial_path() -> None:
    """#11103 (sampled-audit upheld): the CI coverage job's serial leg runs
    the WHOLE ``tests/regressions/`` directory — a deliberate SUPERSET of the
    Makefile's fine-grained ``PYTEST_SERIAL_PATHS`` split. Whole-dir-serial
    is safe (merely slower) and this lane sits off the PR critical path, so
    the coarser shape is the encoded exception, not drift. What must never
    happen silently: a path the Makefile serializes that this leg does not
    execute at all. Pin the superset relation so the three definitions of
    "xdist-unsafe" (test job, coverage job, Makefile) cannot diverge in the
    direction that loses coverage."""
    serial_leg = next(
        run for run in _pytest_run_lines("coverage") if "-n auto" not in run
    )
    leg_paths = {tok for tok in serial_leg.split() if tok.startswith("tests/")}
    assert leg_paths, f"no positional test paths found in serial leg: {serial_leg!r}"

    for path in _makefile_serial_paths():
        covered = path in leg_paths or any(
            path.startswith(d.rstrip("/") + "/") for d in leg_paths
        )
        assert covered, (
            f"Makefile PYTEST_SERIAL_PATHS entry {path!r} is not executed by "
            f"the CI coverage job's serial leg ({sorted(leg_paths)}) — its "
            f"coverage would silently vanish from the trailing floor gate"
        )
