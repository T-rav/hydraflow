"""Regression: closed-escalation churn window keyed on updated_at (#9727).

``DetectorCalibrationLoop``'s 30-day churn window filtered closed
``hitl-escalation`` issues by ``updated_at``, which moves on ANY issue
activity — a comment on an old closed escalation pulled it back into the
window and could fabricate a repeat (review finding, confidence 85). The
correct field is ``closedAt``, which required threading through the
Protocol+adapter+fake triplet (house rule: they move together).

Pins:
- ``GhIssueListItem`` parses ``closedAt`` and defaults it to ``None`` so
  the OPEN listing's narrower projection stays valid (mirror of the
  ``labels`` pattern from #9943).
- ``PRManager.list_closed_issues_by_label`` requests ``closedAt`` in its
  ``--json`` projection and surfaces ``closed_at`` on both the typed-model
  and raw-payload parse paths.
- ``FakeGitHub.list_closed_issues_by_label`` returns the same key
  (fake-fidelity).
- The loop windows on ``closed_at``: an escalation closed outside the
  window but commented on yesterday must NOT count toward churn.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shapes import GhIssueListItem
from detector_calibration_loop import DetectorCalibrationLoop
from events import EventBus
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_pr_manager


@pytest.fixture
def config(tmp_path):  # noqa: ANN001
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(repo_root=tmp_path / "repo")


@pytest.fixture
def event_bus():  # noqa: ANN201
    return EventBus()


class TestShapeCarriesClosedAt:
    def test_closed_at_parsed_from_wire_alias(self) -> None:
        item = GhIssueListItem.model_validate(
            {
                "number": 5,
                "title": "HITL: stuck",
                "body": "",
                "updatedAt": "2026-07-10T00:00:00Z",
                "closedAt": "2026-06-01T12:00:00Z",
            }
        )
        assert item.closed_at == "2026-06-01T12:00:00Z"

    def test_open_listing_narrow_projection_stays_valid(self) -> None:
        """The OPEN listing never projects closedAt — the default keeps
        that parse valid (same contract as the #9943 ``labels`` default)."""
        item = GhIssueListItem.model_validate(
            {"number": 5, "title": "open one", "body": ""}
        )
        assert item.closed_at is None


class TestAdapterProjectsClosedAt:
    @pytest.mark.asyncio
    async def test_projection_requests_and_maps_closed_at(
        self, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        payload = json.dumps(
            [
                {
                    "number": 101,
                    "title": "HITL: gap X unresolved after 3",
                    "body": "",
                    "updatedAt": "2026-07-17T00:00:00Z",
                    "closedAt": "2026-06-01T00:00:00Z",
                }
            ]
        )
        run_gh = AsyncMock(return_value=payload)

        with patch.object(mgr, "_run_gh", run_gh):
            issues = await mgr.list_closed_issues_by_label("hitl-escalation")

        assert run_gh.await_args is not None
        argv = run_gh.await_args.args
        assert "number,title,body,updatedAt,closedAt" in argv
        assert issues[0]["closed_at"] == "2026-06-01T00:00:00Z"
        assert issues[0]["updated_at"] == "2026-07-17T00:00:00Z"

    @pytest.mark.asyncio
    async def test_closed_at_survives_the_raw_payload_fallback(
        self, config, event_bus
    ) -> None:
        """Shape-invalid rows (number as string) still surface closedAt."""
        mgr = make_pr_manager(config, event_bus)
        payload = json.dumps(
            [
                {
                    "number": "not-an-int",
                    "title": "Weird",
                    "closedAt": "2026-06-02T00:00:00Z",
                }
            ]
        )

        with patch.object(mgr, "_run_gh", AsyncMock(return_value=payload)):
            issues = await mgr.list_closed_issues_by_label("hitl-escalation")

        assert issues[0]["closed_at"] == "2026-06-02T00:00:00Z"


class TestFakeGitHubParity:
    @pytest.mark.asyncio
    async def test_fake_rows_carry_closed_at(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(9, "HITL: gap", "x", labels=["hitl-escalation"])
        await gh.close_issue(9)
        gh.set_issue_closed_at(9, "2026-06-03T00:00:00Z")

        rows = await gh.list_closed_issues_by_label("hitl-escalation")

        assert rows[0]["closed_at"] == "2026-06-03T00:00:00Z"


def _loop(tmp_path: Path) -> tuple[DetectorCalibrationLoop, AsyncMock]:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    loop = DetectorCalibrationLoop(
        config=cfg, state=MagicMock(), pr_manager=pr, deps=deps
    )
    return loop, pr


def _row(number: int, closed_days_ago: int, updated_days_ago: int) -> dict:
    now = datetime.now(UTC)
    return {
        "number": number,
        "title": "HITL: fake coverage gap X unresolved after 3",
        "body": "",
        "closed_at": (now - timedelta(days=closed_days_ago)).isoformat(),
        "updated_at": (now - timedelta(days=updated_days_ago)).isoformat(),
    }


class TestLoopWindowsOnCloseTime:
    @pytest.mark.asyncio
    async def test_comment_on_old_close_does_not_fabricate_repeat(
        self, tmp_path: Path
    ) -> None:
        """THE regression: both escalations closed outside the 30-day
        window, both freshly commented on (updated_at = yesterday). The
        old updated_at filter counted them as churn; closedAt must not."""
        loop, pr = _loop(tmp_path)
        pr.list_closed_issues_by_label.return_value = [
            _row(101, closed_days_ago=45, updated_days_ago=1),
            _row(102, closed_days_ago=40, updated_days_ago=1),
        ]

        stats = await loop._do_work()

        assert stats["filed"] == 0
        pr.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_closes_still_detected_when_updated_at_stale(
        self, tmp_path: Path
    ) -> None:
        """Positive control: repeats inside the close window fire even if
        updated_at were somehow older (window keys on closed_at alone)."""
        loop, pr = _loop(tmp_path)
        pr.list_closed_issues_by_label.return_value = [
            _row(101, closed_days_ago=1, updated_days_ago=1),
            _row(102, closed_days_ago=10, updated_days_ago=10),
        ]

        stats = await loop._do_work()

        assert stats["filed"] == 1
