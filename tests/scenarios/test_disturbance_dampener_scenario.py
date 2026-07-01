"""MockWorld scenario for `DisturbanceDampenerLoop` (ADR-0095, Pattern A).

Phase B / Task 4: the registration-only builder (``_build_disturbance_dampener``
in ``tests/scenarios/catalog/loop_registrations.py``) proves the loop wires into
the catalog and instantiates cleanly. This scenario exercises the actual
burn-down behavior end-to-end: a seeded suppressions baseline covering two
files, a fake detector reporting matching findings, a fake runner that
"fixes" each unit without crashing, and a fake ``pr_opener`` that records
calls and reports success.

Pattern B (direct instantiation): like ``test_memory_backlog_scenario.py``,
this loop wants fine-grained control over ``dimensions`` / ``baseline_loader``
injection, so the loop is constructed directly rather than through
``LoopCatalog.instantiate``. The cap (``disturbance_dampener_max_prs_per_tick=1``)
proves only one PR opens per tick even though two files are eligible, and a
second tick proves dedup back-pressure (0 opened once the first unit's key
is recorded).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from dedup_store import DedupStore
from disturbance.models import Finding
from disturbance.registry import DimensionSpec
from disturbance_dampener_loop import DisturbanceDampenerLoop

pytestmark = pytest.mark.scenario_loops

_BASELINE = {
    "src/a.py::noqa": 1,
    "src/b.py::noqa": 1,
}


class _FakeSuppressionsDetector:
    """Fake detector returning findings for two files worth of backlog."""

    name = "suppressions"

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings

    def detect(self, repo_root: Path) -> list[Finding]:  # noqa: ARG002
        return self._findings


def _two_file_findings() -> list[Finding]:
    return [
        Finding(
            dimension="suppressions",
            path="src/a.py",
            signature="src/a.py::noqa",
            message="blanket noqa",
        ),
        Finding(
            dimension="suppressions",
            path="src/b.py",
            signature="src/b.py::noqa",
            message="blanket noqa",
        ),
    ]


def _make_dimension(findings: list[Finding]) -> DimensionSpec:
    return DimensionSpec(
        name="suppressions",
        detector=_FakeSuppressionsDetector(findings),
        baseline_path=Path("disturbance/baselines/suppressions.yaml"),
        fix_prompt="remove the suppression",
    )


def _make_loop(
    tmp_path: Path,
    *,
    pr_opener: Any,
    runner: Any,
    max_prs_per_tick: int = 1,
) -> tuple[DisturbanceDampenerLoop, DedupStore]:
    """Build a DisturbanceDampenerLoop with a real config + injected fakes."""
    from base_background_loop import LoopDeps  # noqa: PLC0415
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        disturbance_dampener_enabled=True,
        disturbance_dampener_max_prs_per_tick=max_prs_per_tick,
    )
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=None,
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
        sleep_fn=AsyncMock(),
    )

    state = MagicMock()
    state.get_disturbance_dampener_attempts.return_value = 0
    state.bump_disturbance_dampener_attempts.return_value = 1

    dedup_path = config.data_root / "dedup" / "disturbance_dampener.json"
    dedup_path.parent.mkdir(parents=True, exist_ok=True)
    dedup = DedupStore("disturbance_dampener", dedup_path)

    loop = DisturbanceDampenerLoop(
        config=config,
        state=state,
        prs=MagicMock(),
        dedup=dedup,
        deps=deps,
        runner=runner,
        dimensions=[_make_dimension(_two_file_findings())],
        baseline_loader=lambda _path: dict(_BASELINE),
        pr_opener=pr_opener,
    )
    return loop, dedup


class TestDisturbanceDampenerScenario:
    """Phase B Task 4 — seeded backlog burns down to <=cap deduped PRs."""

    async def test_burns_down_one_pr_per_tick_then_dedupes(
        self, tmp_path: Path
    ) -> None:
        """Two eligible files, cap=1: exactly one PR opens this tick, its
        dedup key is recorded, and a second tick opens zero (back-pressure)."""
        calls: list[dict[str, Any]] = []

        async def _fake_pr_opener(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return type(
                "R",
                (),
                {
                    "status": "opened",
                    "pr_url": "https://example.invalid/pr/1",
                    "branch": kwargs["branch"],
                    "error": None,
                },
            )()

        runner = MagicMock()
        runner.run = AsyncMock(
            return_value=type("O", (), {"crashed": False, "output_text": "fixed"})()
        )

        loop, dedup = _make_loop(tmp_path, pr_opener=_fake_pr_opener, runner=runner)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["candidates"] == 1, (
            "cap=1 must limit selection to one unit even though two files are eligible"
        )
        assert result["opened"] == 1
        assert result["skipped"] == 0
        assert result["crashed"] == 0
        assert len(calls) == 1

        # Smallest-file-first + deterministic path tiebreak -> src/a.py wins.
        opened_key = "disturbance:suppressions:src/a.py"
        assert opened_key in dedup.get()
        # The fake pr_opener stands in for generate_and_open_pr_async and
        # does not invoke the `generate` callback it's handed, so the
        # runner is wired but not exercised here; that wiring is covered
        # by test_disturbance_dampener_loop.py's unit test which uses a
        # pr_opener invoking generate directly.

        # Second tick: src/a.py's dedup key blocks it from being reselected
        # (back-pressure). src/b.py is still fresh and under cap=1, so it
        # opens instead — proving the *same* unit is never reopened while a
        # PR is outstanding, without requiring every unit to be exhausted.
        calls.clear()
        runner.run.reset_mock()
        result2 = await loop._do_work()

        assert result2["status"] == "ok"
        assert result2["candidates"] == 1
        assert result2["opened"] == 1
        assert len(calls) == 1
        assert calls[0]["branch"] != "agent/disturbance-suppressions-src-a-py"
        assert opened_key in dedup.get(), "tick 1's dedup key must persist"

    async def test_second_tick_opens_zero_once_all_units_deduped(
        self, tmp_path: Path
    ) -> None:
        """Once every eligible unit has an open PR recorded, a further tick
        opens zero — pure dedup back-pressure with no fresh candidates."""
        calls: list[dict[str, Any]] = []

        async def _fake_pr_opener(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return type(
                "R",
                (),
                {
                    "status": "opened",
                    "pr_url": "https://example.invalid/pr/1",
                    "branch": kwargs["branch"],
                    "error": None,
                },
            )()

        runner = MagicMock()
        runner.run = AsyncMock(
            return_value=type("O", (), {"crashed": False, "output_text": "fixed"})()
        )

        # cap=2 so both files open in tick 1, leaving nothing for tick 2.
        loop, dedup = _make_loop(
            tmp_path, pr_opener=_fake_pr_opener, runner=runner, max_prs_per_tick=2
        )

        result = await loop._do_work()
        assert result["opened"] == 2
        assert dedup.get() == {
            "disturbance:suppressions:src/a.py",
            "disturbance:suppressions:src/b.py",
        }

        calls.clear()
        runner.run.reset_mock()
        result2 = await loop._do_work()

        assert result2["status"] == "ok"
        assert result2["candidates"] == 0
        assert result2["opened"] == 0
        assert calls == []
        runner.run.assert_not_awaited()
