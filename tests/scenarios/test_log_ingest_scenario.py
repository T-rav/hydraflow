"""MockWorld scenario: LogIngestLoop end-to-end against the FakeGitHub port.

Exercises a full tick of the real ``LogIngestLoop._do_work`` wired to the
scenario harness's ``FakeGitHub`` PRPort and a real ``StateTracker``. Unlike
the unit tests (which mock the port), this verifies loop ↔ port ↔ state
integration: the cursor-from-now prime, real issue creation through the Fake,
the embedded dedup marker, and second-tick dedup against the open issue the
Fake now holds.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from log_ingest_loop import LogIngestLoop
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _line(level: str, msg: str, logger: str = "hydraflow.pipeline") -> str:
    return json.dumps(
        {"ts": "2026-06-04T10:00:00Z", "level": level, "msg": msg, "logger": logger}
    )


def _build_loop(world: MockWorld) -> tuple[LogIngestLoop, Path]:
    config = world.harness.config
    log_file = Path(config.data_root) / "logs" / "hydraflow.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch()

    # Every awaited PRPort method must resolve to a coroutine. FakeGitHub
    # already implements create_issue / list_issues_by_label as real coroutines,
    # so no AsyncMock shims are needed here — this is the fidelity win of using
    # the real Fake over a bare MagicMock.
    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _n: True,
        sleep_fn=AsyncMock(),
    )
    loop = LogIngestLoop(
        config=config,
        prs=world.github,
        deps=deps,
        state=world.harness.state,
    )
    return loop, log_file


class TestLogIngestScenario:
    """Full-tick scenario coverage for the log-ingest caretaker loop."""

    async def test_tick_primes_then_files_then_dedups(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        loop, log_file = _build_loop(world)

        # Historical errors present before the first tick must NOT be filed.
        with log_file.open("a", encoding="utf-8") as fh:
            for i in range(3):
                fh.write(_line("ERROR", f"historical boom {i}") + "\n")

        prime = await loop._do_work()
        assert prime == {"status": "primed", "files_primed": 1}
        # No issues filed during priming.
        assert await world.github.list_issues_by_label(config_label(world)) == []

        # New, post-prime recurring error appended to the live log.
        with log_file.open("a", encoding="utf-8") as fh:
            for i in range(4):
                fh.write(_line("ERROR", f"connection reset after {i}s") + "\n")

        filed = await loop._do_work()
        assert filed["status"] == "ok"
        assert filed["filed"] == 1

        issues = await world.github.list_issues_by_label(config_label(world))
        assert len(issues) == 1
        body = issues[0]["body"]
        assert "<!-- [log-ingest:" in body
        # The pipeline entry label (find_label) is also attached so triage
        # picks the issue up — it therefore appears in that label's listing too.
        find_lbl = world.harness.config.find_label[0]
        under_find = await world.github.list_issues_by_label(find_lbl)
        assert any(i["number"] == issues[0]["number"] for i in under_find)

        # Second tick with the same signature (different trailing number) must
        # dedup against the open issue the Fake now holds — no new issue.
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(_line("ERROR", "connection reset after 99s") + "\n")

        again = await loop._do_work()
        assert again["filed"] == 0
        assert again["skipped"] == 1
        issues_after = await world.github.list_issues_by_label(config_label(world))
        assert len(issues_after) == 1

    async def test_disabled_is_noop(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        world.harness.config.log_ingest_loop_enabled = False
        loop, log_file = _build_loop(world)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(_line("ERROR", "should be ignored") + "\n")

        result = await loop._do_work()
        assert result == {"status": "config_disabled"}
        assert await world.github.list_issues_by_label(config_label(world)) == []


def config_label(world: MockWorld) -> str:
    return world.harness.config.log_ingest_label
