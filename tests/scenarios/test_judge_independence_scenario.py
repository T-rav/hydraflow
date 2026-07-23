"""MockWorld scenario for judge-independence + fail-visible dispatch (#10371).

End-to-end over the real EventBus + FakeGitHub + the on-disk fail-open ledger,
proving the pieces integrate (not just each unit in isolation):

* ``test_classed_change_routes_and_fail_open_is_ledgered_and_alarmed`` — a
  classed (structural) change routed through ``PostVerifyAdvisor`` dispatches
  its verdict to the independent model family and records an independent
  ``classed_verdict``; a subsequent dispatch failure writes a ``fail_open``
  ledger row AND publishes a ``judge_fail_open`` SYSTEM_ALERT on the bus.
* ``test_fail_open_rate_breach_files_hydraflow_find`` — a seeded fail-open spike
  drives ``FailOpenMonitorLoop`` to file exactly one ``hydraflow-find`` issue
  through the real ``FakeGitHub.create_issue`` path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import judge_independence as ji
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_STRUCTURAL_DIFF = (
    "diff --git a/docs/adr/0099-x.md b/docs/adr/0099-x.md\n"
    "--- a/docs/adr/0099-x.md\n"
    "+++ b/docs/adr/0099-x.md\n"
    "@@ -1 +1 @@\n-a\n+b\n"
)


class _ScriptedRunner:
    """Returns a canned payload, or raises for the fail-open leg."""

    def __init__(self, payload: str | Exception) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, *, model: str, subagent_type: str, prompt: str, role: str
    ) -> str:
        self.calls.append({"model": model, "role": role})
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _config(world: MockWorld, tmp_path: Path) -> Any:
    config = world.harness.config
    object.__setattr__(config, "data_root", tmp_path / "data")
    return config


class TestJudgeIndependenceScenario:
    async def test_classed_change_routes_and_fail_open_is_ledgered_and_alarmed(
        self, tmp_path: Path
    ) -> None:
        from review_advisor import (
            SURFACE_ADVISOR_CONFIGS,
            PostVerifyAdvisor,
            PostVerifyInput,
        )

        world = MockWorld(tmp_path)
        config = _config(world, tmp_path)
        bus = world.harness.bus
        ledger = ji.ledger_path_for(config)

        # A classed change routes its verdict to the independent family.
        ok_runner = _ScriptedRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=ok_runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            ledger_path=ledger,
            event_bus=bus,
            pr_number=4242,
            judge_independence_enabled=True,
            independent_model="gpt-4o",
        )
        await advisor.run(
            PostVerifyInput(
                surface="pr_review",
                diff=_STRUCTURAL_DIFF,
                executor_verdict_summary="approved",
            )
        )
        assert ok_runner.calls[0]["model"] == "gpt-4o"
        classed = [
            r for r in ji.read_records(ledger) if r["kind"] == ji.KIND_CLASSED_VERDICT
        ]
        assert classed and classed[0]["independent"] is True
        assert classed[0]["judge_family"] == "openai"

        # A dispatch failure on the classed change is ledgered AND alarmed.
        boom_runner = _ScriptedRunner(RuntimeError("judge unavailable"))
        advisor_fail = PostVerifyAdvisor(
            runner=boom_runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            ledger_path=ledger,
            event_bus=bus,
            pr_number=4242,
            judge_independence_enabled=True,
            independent_model="gpt-4o",
        )
        result = await advisor_fail.run(
            PostVerifyInput(
                surface="pr_review",
                diff=_STRUCTURAL_DIFF,
                executor_verdict_summary="approved",
            )
        )
        assert result.verdict == "APPROVE"  # non-self-mod fails open, ledgered
        fail_open = [
            r for r in ji.read_records(ledger) if r["kind"] == ji.KIND_FAIL_OPEN
        ]
        assert len(fail_open) == 1
        assert "structural" in fail_open[0]["failure_class"]
        alarms = [
            e for e in bus.get_history() if e.data.get("kind") == "judge_fail_open"
        ]
        assert len(alarms) == 1
        assert alarms[0].data["pr"] == 4242

    async def test_fail_open_rate_breach_files_hydraflow_find(
        self, tmp_path: Path
    ) -> None:
        from fail_open_monitor_loop import FailOpenMonitorLoop
        from tests.helpers import make_bg_loop_deps

        world = MockWorld(tmp_path)
        config = _config(world, tmp_path)
        github = world.github

        ledger = ji.ledger_path_for(config)
        for i, d in enumerate(["2026-07-01", "2026-07-02", "2026-07-03"]):
            ji.record_fail_open(
                ledger,
                lens=None,
                pr=i,
                surface="pr_review",
                classes=frozenset(),
                disposition=ji.FailOpenDisposition.FAIL_OPEN_LEDGERED,
                reason="x",
                ts=f"{d}T00:00:00+00:00",
            )
        for i in range(12):
            ji.record_fail_open(
                ledger,
                lens=None,
                pr=200 + i,
                surface="pr_review",
                classes=frozenset(),
                disposition=ji.FailOpenDisposition.FAIL_OPEN_LEDGERED,
                reason="x",
                ts="2026-07-04T00:00:00+00:00",
            )

        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        object.__setattr__(bg.config, "fail_open_monitor_loop_enabled", True)

        from unittest.mock import MagicMock

        dedup = MagicMock()
        store: set[str] = set()
        dedup.get.side_effect = lambda: set(store)
        dedup.set_all.side_effect = lambda v: (store.clear(), store.update(v))

        loop = FailOpenMonitorLoop(
            config=bg.config, pr_manager=github, dedup=dedup, deps=bg.loop_deps
        )
        result = await loop._do_work()

        assert result["breached"] is True
        assert result["filed"] == 1
        assert len(github._issues) == 1
        (issue,) = github._issues.values()
        assert "hydraflow-find" in issue.labels
        assert "judge-independence" in issue.labels
