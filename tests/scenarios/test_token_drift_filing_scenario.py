"""MockWorld scenario for the token-drift filing actuator (#11442).

End-to-end over FakeGitHub + ``ErosionMetricsLoop`` (the host cadence) +
a REAL ``DedupStore`` on disk — a MagicMock dedup would make the dedup
assertions below pass vacuously (see ``loop_registrations._build_erosion_metrics``'s
docstring). ``config.repo_root`` points at a directory that is not a git
repo, so the erosion sensors themselves stay inert (``head_sha_unavailable``)
and every issue filed in this scenario comes from the token-drift actuator.

Covers the issue's full acceptance path:

* ``test_sustained_drift_files_one_issue`` — a source whose token share grows
  past the control band within one trailing window gets exactly one
  ``token-drift`` issue filed.
* ``test_second_daily_run_dedupes`` — an identical second daily tick (same
  ISO week, same source) files nothing further.
* ``test_different_source_in_same_week_files_separately`` — a second source
  drifting within the SAME ISO week gets its own, separate issue.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.scenario_loops


def _row(source: str, tokens: int) -> dict[str, Any]:
    return {"issue_number": 1, "source": source, "total_tokens": tokens}


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _build_loop(tmp_path: Path, github: Any) -> Any:
    from dedup_store import DedupStore
    from erosion_metrics_loop import ErosionMetricsLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", tmp_path / "not_a_git_repo")
    object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
    dedup = DedupStore("erosion_metrics_filed_findings", tmp_path / "dedup.json")
    return ErosionMetricsLoop(
        config=bg.config,
        pr_manager=github,
        state=_state(),
        dedup=dedup,
        deps=bg.loop_deps,
    ), bg.config


def _state() -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    state.get_erosion_last_processed_sha.return_value = ""
    return state


class TestTokenDriftFilingScenario:
    async def test_sustained_drift_files_one_issue(self, tmp_path: Path) -> None:
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path)
        loop, config = _build_loop(tmp_path, world.github)

        before = [_row("implementer", 100), _row("planner", 100)] * 50
        after = [_row("implementer", 900), _row("planner", 100)] * 50
        _write_rows(config.cost_inferences_path, before + after)

        result = await loop._do_work()

        assert result["token_drift_filed"] == 1
        assert len(world.github._issues) == 1
        (issue,) = world.github._issues.values()
        assert "token-drift" in issue.labels
        assert "hydraflow-find" in issue.labels
        assert "implementer" in issue.title

    async def test_second_daily_run_dedupes(self, tmp_path: Path) -> None:
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path)
        loop, config = _build_loop(tmp_path, world.github)

        before = [_row("implementer", 100), _row("planner", 100)] * 50
        after = [_row("implementer", 900), _row("planner", 100)] * 50
        _write_rows(config.cost_inferences_path, before + after)

        first = await loop._do_work()
        second = await loop._do_work()

        assert first["token_drift_filed"] == 1
        assert second["token_drift_filed"] == 0
        assert len(world.github._issues) == 1

    async def test_different_source_in_same_week_files_separately(
        self, tmp_path: Path
    ) -> None:
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path)
        loop, config = _build_loop(tmp_path, world.github)

        before = [_row("implementer", 100), _row("planner", 100)] * 50
        after = [_row("implementer", 900), _row("planner", 100)] * 50
        _write_rows(config.cost_inferences_path, before + after)

        first = await loop._do_work()
        assert first["token_drift_filed"] == 1

        # A second source ("reviewer") drifts within the same window: append
        # its own before/after halves so the NEW trailing window's older half
        # is entirely the tick-1 data (implementer/planner, now flat) and the
        # newer half is entirely reviewer's before->after growth.
        reviewer_before = [_row("reviewer", 100), _row("planner", 100)] * 50
        reviewer_after = [_row("reviewer", 900), _row("planner", 100)] * 50
        _write_rows(config.cost_inferences_path, reviewer_before + reviewer_after)

        second = await loop._do_work()

        assert second["token_drift_filed"] == 1
        assert len(world.github._issues) == 2
        titles = [issue.title for issue in world.github._issues.values()]
        assert any("implementer" in t for t in titles)
        assert any("reviewer" in t for t in titles)
