"""Regression: fake-coverage rollups had no auto-close path (#9541).

When the last uncovered adapter-surface method gained a cassette,
``_clear_rollup_state`` in ``src/fake_coverage_auditor_loop.py`` repainted the
rollup body to the "all covered" view and cleared dedup/attempt state but left
the GitHub issue OPEN, relying on a human to close it — the #9183 dead-letter
shape. Other caretaker loops auto-close their find-issues on recovery (#9359
rollup rollout; #10015 streak-escalation precedent).

Pins (#9541):
- red → red → recovery: the tracked rollup issue is repainted (strikethrough
  trajectory), commented, and CLOSED on the recovery tick; attempts, the
  rollup mapping, and the dedup key are all cleared.
- a later regression re-files a FRESH rollup issue (new number, attempt
  counter restarted) rather than resurrecting the closed one.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from fake_coverage_auditor_loop import FakeCoverageAuditorLoop
from state import StateTracker

ROLLUP_ISSUE = 4242
REFILED_ISSUE = 5000
KEY = "FakeGitHub:adapter-surface"
DEDUP_KEY = "fake_coverage_auditor:FakeGitHub:adapter-surface"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Auditor wired to a REAL StateTracker/DedupStore over a tiny repo tree.

    The memory-pinned harness shape: ``repo_root`` must point at the seeded
    tree or the catalog scan finds nothing. ``_list_open_rollup_titles`` is
    replaced by a mutable set the test drives (it is a raw ``gh`` read), and
    escalation reconciles run against empty AsyncMock port listings.
    """
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data", repo="hydra/hydraflow", repo_root=tmp_path
    )
    state = StateTracker(tmp_path / "state.json")
    dedup = DedupStore("fake_coverage", tmp_path / "dedup.json")
    pr = AsyncMock()
    pr.create_issue = AsyncMock(side_effect=[ROLLUP_ISSUE, REFILED_ISSUE])
    pr.close_issue = AsyncMock(return_value=True)
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )

    open_titles: set[str] = set()

    async def fake_list_titles() -> set[str]:
        return set(open_titles)

    monkeypatch.setattr(loop, "_list_open_rollup_titles", fake_list_titles)

    fake_dir = tmp_path / "src" / "mockworld" / "fakes"
    fake_dir.mkdir(parents=True)
    (fake_dir / "fake_github.py").write_text(
        "class FakeGitHub:\n    async def missing(self): ...\n"
    )
    cassettes = tmp_path / "tests" / "trust" / "contracts" / "cassettes" / "github"
    cassettes.mkdir(parents=True)

    return loop, pr, state, dedup, open_titles, cassettes


def _record_cassette(cassettes: Path) -> None:
    (cassettes / "missing.yaml").write_text(
        yaml.safe_dump({"input": {"command": "missing"}, "output": {}})
    )


async def _drive_red_red_recovery(world) -> dict:
    """Tick 1 red (file), tick 2 red (update), tick 3 recovered. Returns
    the recovery tick's stats."""
    loop, pr, state, dedup, open_titles, cassettes = world

    stats1 = await loop._do_work()
    assert stats1["filed"] == 1
    assert state.get_fake_coverage_rollup_issue(KEY) == ROLLUP_ISSUE
    open_titles.add(pr.create_issue.await_args.args[0])

    stats2 = await loop._do_work()
    assert stats2["updated"] == 1
    assert pr.create_issue.await_count == 1  # updated in place, not re-filed

    _record_cassette(cassettes)
    return await loop._do_work()


async def test_red_red_recovery_autocloses_rollup(world) -> None:
    loop, pr, state, dedup, open_titles, cassettes = world

    stats3 = await _drive_red_red_recovery(world)

    # The rollup issue was commented and closed on the recovery tick.
    assert stats3["rollups_closed"] == 1
    pr.close_issue.assert_awaited_once_with(ROLLUP_ISSUE)
    assert pr.post_comment.await_args.args[0] == ROLLUP_ISSUE
    # Final body records the recovery trajectory, not a stale gap list.
    final_body = pr.update_issue_body.await_args.args[1]
    assert pr.update_issue_body.await_args.args[0] == ROLLUP_ISSUE
    assert "~~`missing`~~" in final_body
    # Tracking fully cleared: mapping, attempt counter, dedup key.
    assert state.get_fake_coverage_rollup_issue(KEY) is None
    assert state.get_fake_coverage_attempts(KEY) == 0
    assert DEDUP_KEY not in dedup.get()


async def test_regression_after_autoclose_refiles_fresh(world) -> None:
    loop, pr, state, dedup, open_titles, cassettes = world

    await _drive_red_red_recovery(world)
    open_titles.clear()  # the rollup was auto-closed

    # The regression returns: the cassette disappears again.
    (cassettes / "missing.yaml").unlink()

    stats4 = await loop._do_work()

    # A FRESH rollup was filed (new number), not the closed one resurrected.
    assert stats4["filed"] == 1
    assert pr.create_issue.await_count == 2
    assert state.get_fake_coverage_rollup_issue(KEY) == REFILED_ISSUE
    # Attempt counter restarted from scratch (1 of 3), so the 3-strikes
    # escalation clock is fresh for the new streak.
    assert state.get_fake_coverage_attempts(KEY) == 1
    # And only the original close happened — the fresh issue stays open.
    pr.close_issue.assert_awaited_once_with(ROLLUP_ISSUE)
