"""Regression: IssueRefinementLoop v1 follow-ups (#10025).

Pins three bug shapes from the #9957 v1 build's final whole-branch review:

- FakeGitHub.get_issue_state fail-OPENED for unknown issues (returned "OPEN"),
  while prod PRManager.get_issue_state fail-CLOSES with "UNKNOWN" when the gh
  read errors. The fake was fail-open exactly at the refinement TOCTOU
  stale-close guard, making the still-open re-check pass vacuously for any
  issue the fake never saw.
- The refinement stale-close guard must therefore ABORT (not close) when
  either side of a judged pair reads UNKNOWN.
- gh defaults closes to stateReason=COMPLETED, so refinement auto-closes read
  as "resolved" to every get_issue_state consumer. The close now threads
  reason="not planned" through the port triplet and records NOT_PLANNED.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from issue_refinement import AutoClose
from issue_refinement_loop import _REFINEMENT_AUTO_LABEL, IssueRefinementLoop
from mockworld.fakes.fake_github import FakeGitHub
from state import StateTracker


class _NeverCalledLLM:
    async def complete(self, prompt: str) -> str:
        raise AssertionError("no LLM call expected in this regression")


def _make_loop(tmp_path: Path, gh: FakeGitHub) -> IssueRefinementLoop:
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    return IssueRefinementLoop(
        config=HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow"),
        state=StateTracker(state_file=tmp_path / "state.json"),
        pr_manager=gh,
        dedup=DedupStore("issue_refinement", tmp_path / "dedup.json"),
        deps=deps,
        refinement_llm=_NeverCalledLLM(),
    )


async def test_fake_github_unknown_issue_state_matches_prod_fail_closed() -> None:
    """Unknown issue -> "UNKNOWN" (prod parity), never a vacuous "OPEN"."""
    gh = FakeGitHub()
    gh.add_issue(101, "Seeded issue", "body")

    assert await gh.get_issue_state(101) == "OPEN"
    assert await gh.get_issue_state(999) == "UNKNOWN"


async def test_fake_github_close_reason_maps_to_state_reason() -> None:
    """close_issue(reason="not planned") -> NOT_PLANNED; default -> COMPLETED."""
    gh = FakeGitHub()
    gh.add_issue(101, "Dedup victim", "body")
    gh.add_issue(102, "Genuinely fixed", "body")

    await gh.close_issue(101, reason="not planned")
    await gh.close_issue(102)

    assert await gh.get_issue_state(101) == "NOT_PLANNED"
    assert await gh.get_issue_state(102) == "COMPLETED"


async def test_stale_guard_aborts_close_when_issue_state_unknown(tmp_path) -> None:
    """The TOCTOU stale-close guard fails CLOSED on an UNKNOWN read: before
    the fake-fidelity fix it passed vacuously and the close went through."""
    gh = FakeGitHub()
    gh.add_issue(102, "The judged duplicate", "body")  # canonical 101 unknown
    loop = _make_loop(tmp_path, gh)
    close = AutoClose(
        canonical=101, duplicate=102, evidence="judged earlier", confidence="high"
    )

    with pytest.raises(RuntimeError, match="stale judgment"):
        await loop._apply_auto_close(close)

    assert gh._issues[102].state == "open"
    assert _REFINEMENT_AUTO_LABEL not in gh._issues[102].labels
