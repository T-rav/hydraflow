"""Regression #11505: RC promotion PR #11478 failed CI on a test-fixture
wall-clock time-bomb — and the advisory lane built to catch that exact class
never ran the file holding it.

**What actually failed.** ``Tests`` reported ``1 failed, 22678 passed`` on
run 32434663772; ``CI Gate`` failed 4s later because ``Tests`` did. The one
failure was::

    tests/test_rc_budget_loop.py:583:
        assert [r["databaseId"] for r in runs] == [2]
    E   assert [] == [2]

Not a regression, not a flake, not environmental — a time-bomb.
``rc_budget_loop._fetch_recent_runs`` cuts its window at
``datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)`` (src/rc_budget_loop.py:260,
``_WINDOW_DAYS = 30``), while the fixture on ``rc/2026-08-20-0621`` hardcoded
the surviving run at ``created_at="2026-07-21T23:21:55Z"``. The RC PR opened
2026-08-20T06:21:07Z, when the cutoff was 2026-07-21T06:21 and the row was
17 hours inside the window. CI re-ran 2026-08-21T01:55:45Z, when the cutoff
had advanced to 2026-07-22T01:55 and the row fell 2h34m *outside* it. Same
bytes, same ``src/``, different wall clock.

**Status of the symptom.** Already fixed, incidentally, by commit ``3fbccc70c``
(PR #11487, trailer ``test: make RC budget run timestamps now-relative``),
which landed on staging 2026-08-21T00:10Z — 1h45m before the failing run, but
~18h after ``rc/2026-08-20-0621`` was cut, so the RC branch never carried it.
``src/rc_budget_loop.py`` is byte-identical across the fix; the defect lived
entirely in the fixture.

**What is still present.** This class is a named repo principle —
``TEST-WALLCLOCK-TIMEBOMB-001`` (docs/wiki/gotchas.md, #11047) — with a
purpose-built detonator range: the ``_time_travel`` autouse fixture
(tests/conftest.py) plus a hand-maintained file list duplicated in the
``time-travel`` Makefile target and the ``Time Travel (advisory)`` CI job.
``tests/test_rc_budget_loop.py`` is in neither list, so
``Time Travel (advisory)`` passed on run 32434663772 while the very bomb it
exists to arm blew up ``Tests`` in the same run. The sibling pin
``tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py``
*was* made now-relative on 2026-08-14 (it carries the
``TEST-WALLCLOCK-TIMEBOMB-001`` marker) — the lane covers ``tests/regressions/``,
so it only ever imports the twin unit-test module and never executes its tests.
The twin outside the lane kept its hardcoded dates for another week and
detonated on the RC.

Pins below, in order:

* ``test_prefix_fixture_detonates_on_the_clock_alone`` — replays the pre-fix
  payload verbatim through the real loop at both instants. GREEN: fixes the
  diagnosis permanently.
* ``test_live_fixture_survives_a_far_future_clock`` — re-executes the real
  unit test under a +400d clock. GREEN today, RED the moment anyone
  re-hardcodes those timestamps.
* ``test_time_travel_lane_covers_the_file_that_detonated`` — RED today: the
  detonator range does not cover ``tests/test_rc_budget_loop.py``.
* ``test_lane_coverage_predicate_is_not_vacuous`` — liveness counter-pin for
  the check above.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from freezegun import freeze_time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.test_rc_budget_loop import _loop, loop_env  # noqa: F401
from tests.test_rc_budget_loop import (
    test_fetch_recent_runs_excludes_cancelled_runs as _live_unit_test,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The file whose fixture detonated on RC PR #11478.
_DETONATED_FILE = "tests/test_rc_budget_loop.py"

#: The payload exactly as it stood on ``rc/2026-08-20-0621``, before
#: ``3fbccc70c`` made the timestamps now-relative.
_PREFIX_ROWS = [
    {
        "id": 1,
        "url": "u1",
        "status": "completed",
        "conclusion": "cancelled",
        "created_at": "2026-07-22T02:16:51Z",
        "run_started_at": "2026-07-22T01:31:51Z",
        "updated_at": "2026-07-22T02:16:51Z",
    },
    {
        "id": 2,
        "url": "u2",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-07-21T23:21:55Z",
        "run_started_at": "2026-07-21T23:21:50Z",
        "updated_at": "2026-07-21T23:21:55Z",
    },
]

#: When PR #11478 opened — the fixture was still inside the 30-day window.
_PR_OPENED = datetime(2026, 8, 20, 6, 21, 7, tzinfo=UTC)
#: When its ``Tests`` job re-ran and reported ``assert [] == [2]``.
_CI_RERAN = datetime(2026, 8, 21, 1, 55, 45, tzinfo=UTC)


async def _survivors(loop_env, rows: list[dict]) -> list[int]:  # noqa: F811
    loop = _loop(loop_env)
    loop._github_cache.get_rc_workflow_runs = AsyncMock(return_value=rows)
    return [r["databaseId"] for r in await loop._fetch_recent_runs()]


async def test_prefix_fixture_detonates_on_the_clock_alone(loop_env) -> None:  # noqa: F811
    """The pre-fix payload passes at PR-open and fails at CI-re-run.

    Identical input, identical ``src/rc_budget_loop.py`` — only
    ``datetime.now(UTC)`` moved. That asymmetry IS the #11505 diagnosis:
    a systematic, reproducible failure with no code change on either side
    is a time-bomb, not a flake (TEST-WALLCLOCK-TIMEBOMB-001).
    """
    with freeze_time(_PR_OPENED):
        assert await _survivors(loop_env, _PREFIX_ROWS) == [2]

    with freeze_time(_CI_RERAN):
        # The exact failure GitHub reported on run 32434663772.
        assert await _survivors(loop_env, _PREFIX_ROWS) == []


async def test_live_fixture_survives_a_far_future_clock(loop_env) -> None:  # noqa: F811
    """Re-run the real unit test with the clock pushed far past any window.

    This is the forward guard the RC needed: it executes
    ``tests/test_rc_budget_loop.py::test_fetch_recent_runs_excludes_cancelled_runs``
    itself, so re-hardcoding those timestamps re-detonates here instead of on
    a promotion PR. 400 days clears ``_WINDOW_DAYS`` (30) by an order of
    magnitude, so it cannot be satisfied by a merely *newer* hardcoded date.
    """
    far_future = datetime.now(UTC) + timedelta(days=400)
    with freeze_time(far_future, tick=True):
        await _live_unit_test(loop_env)


def _lane_paths_from_makefile() -> list[str]:
    """Extract the pytest path arguments of the ``time-travel`` make target."""
    lines = (_REPO_ROOT / "Makefile").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("time-travel:"))
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    return re.findall(r"(?<![\w/.-])tests/[\w/.-]*", "\n".join(recipe))


def _lane_paths_from_ci_workflow() -> list[str]:
    """Extract the pytest path arguments of the ``Time Travel`` CI job."""
    workflow = yaml.safe_load((_REPO_ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["time-travel"]["steps"]
    script = "\n".join(str(step.get("run", "")) for step in steps)
    return re.findall(r"(?<![\w/.-])tests/[\w/.-]*", script)


def _covers(lane_paths: list[str], target: str) -> bool:
    """True when *target* is collected by *lane_paths*.

    Satisfied by either accepted remedy: naming the file outright, or
    widening the lane to a directory (``tests/`` or ``tests/regressions/``-style
    prefix) that contains it.
    """
    return any(
        path == target or (path.endswith("/") and target.startswith(path))
        for path in lane_paths
    )


@pytest.mark.parametrize(
    ("lane", "reader"),
    [
        ("Makefile time-travel target", _lane_paths_from_makefile),
        ("Time Travel (advisory) CI job", _lane_paths_from_ci_workflow),
    ],
)
def test_time_travel_lane_covers_the_file_that_detonated(lane, reader) -> None:
    """The detonator range must arm the file that blew up RC #11478.

    ``Time Travel (advisory)`` reported PASS on run 32434663772 while
    ``tests/test_rc_budget_loop.py`` — carrying the bomb — failed ``Tests`` in
    the same run. The lane collects ``tests/regressions/``, which only
    *imports* that module (via the #10215 sibling pin's
    ``from tests.test_rc_budget_loop import _loop, loop_env``) and never
    executes its tests, so the module's own hardcoded fixtures were never
    armed.
    """
    lane_paths = reader()
    assert lane_paths, f"{lane}: no pytest paths parsed — reader is stale"
    assert _covers(lane_paths, _DETONATED_FILE), (
        f"{lane} does not arm {_DETONATED_FILE} (#11505). Lane paths: {lane_paths}"
    )


def test_lane_coverage_predicate_is_not_vacuous() -> None:
    """Liveness counter-pin: the coverage check can actually fail and pass.

    Without this, a ``_covers`` that always returned True would let the pin
    above go green on a lane that arms nothing.
    """
    assert not _covers(
        ["tests/regressions/", "tests/test_staleness.py"], _DETONATED_FILE
    )
    assert _covers(["tests/regressions/", _DETONATED_FILE], _DETONATED_FILE)
    assert _covers(["tests/"], _DETONATED_FILE)
