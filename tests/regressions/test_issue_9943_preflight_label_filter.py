"""Regression: preflight human-required filter was a silent no-op (#9943).

``AutoAgentPreflightLoop._poll_eligible_issues`` filters on
``issue["labels"]``, but neither ``PRManager.list_issues_by_label`` (which
projected only ``number,title,body,updatedAt``) nor
``FakeGitHub.list_issues_by_label`` returned a ``labels`` key — the filter
always saw an empty label set and never removed anything, so exhausted
``human-required`` escalations were re-polled every tick. Unit tests hid
the bug by hand-seeding ``labels`` dicts the adapters never produced.

Pins:
- The adapter projects ``labels`` and maps them in gh wire shape
  (``[{"name": ...}]``), on both the typed-model and raw-payload parse paths.
- FakeGitHub returns the same wire shape (fake-fidelity).
- The preflight filter excludes human-required issues end-to-end when fed
  through the REAL FakeGitHub port rather than hand-seeded dicts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_bg_loop_deps, make_pr_manager

_GH_PAYLOAD = json.dumps(
    [
        {
            "number": 7,
            "title": "Stuck",
            "body": "needs help",
            "updatedAt": "2026-07-01T00:00:00Z",
            "labels": [
                {"name": "hitl-escalation", "color": "ff0000"},
                {"name": "human-required", "color": "00ff00"},
            ],
        },
        {
            "number": 8,
            "title": "Fresh",
            "body": "retry me",
            "updatedAt": "2026-07-02T00:00:00Z",
            "labels": [{"name": "hitl-escalation", "color": "ff0000"}],
        },
    ]
)


class TestAdapterProjectsLabels:
    @pytest.mark.asyncio
    async def test_projection_includes_labels_and_maps_wire_shape(
        self, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        run_gh = AsyncMock(return_value=_GH_PAYLOAD)

        with patch.object(mgr, "_run_gh", run_gh):
            issues = await mgr.list_issues_by_label("hitl-escalation")

        assert run_gh.await_args is not None
        argv = run_gh.await_args.args
        assert "number,title,body,updatedAt,labels" in argv
        assert issues[0]["labels"] == [
            {"name": "hitl-escalation"},
            {"name": "human-required"},
        ]
        assert issues[1]["labels"] == [{"name": "hitl-escalation"}]

    @pytest.mark.asyncio
    async def test_labels_survive_the_raw_payload_fallback(
        self, config, event_bus
    ) -> None:
        """Shape-invalid rows (number as string) still surface their labels."""
        mgr = make_pr_manager(config, event_bus)
        payload = json.dumps(
            [
                {
                    "number": "not-an-int",
                    "title": "Weird",
                    "labels": [{"name": "human-required"}],
                }
            ]
        )

        with patch.object(mgr, "_run_gh", AsyncMock(return_value=payload)):
            issues = await mgr.list_issues_by_label("hitl-escalation")

        assert issues[0]["labels"] == [{"name": "human-required"}]


class TestFakeGitHubParity:
    @pytest.mark.asyncio
    async def test_fake_returns_wire_shape_labels(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(7, "Stuck", "x", labels=["hitl-escalation", "human-required"])

        issues = await gh.list_issues_by_label("hitl-escalation")

        assert issues[0]["labels"] == [
            {"name": "hitl-escalation"},
            {"name": "human-required"},
        ]


class TestPreflightFilterEndToEnd:
    def _make_loop(self, tmp_path: Path, prs) -> AutoAgentPreflightLoop:
        deps = make_bg_loop_deps(tmp_path)
        state = MagicMock()
        state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
        state.get_auto_agent_attempts = MagicMock(return_value=0)
        audit = MagicMock()
        audit.daily_spend = MagicMock(return_value=0.0)
        return AutoAgentPreflightLoop(
            config=deps.config,
            state=state,
            pr_manager=prs,
            wiki_store=None,
            audit_store=audit,
            deps=deps.loop_deps,
        )

    @pytest.mark.asyncio
    async def test_human_required_filtered_via_real_fake_port(
        self, tmp_path: Path
    ) -> None:
        """The filter works against what the port ACTUALLY returns."""
        gh = FakeGitHub()
        gh.add_issue(7, "Stuck", "x", labels=["hitl-escalation", "human-required"])
        gh.add_issue(8, "Fresh", "y", labels=["hitl-escalation"])
        loop = self._make_loop(tmp_path, gh)

        eligible = await loop._poll_eligible_issues()

        assert [issue["number"] for issue in eligible] == [8]
