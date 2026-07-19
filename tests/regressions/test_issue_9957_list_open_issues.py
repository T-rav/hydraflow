"""Regression: PRPort.list_open_issues atomic triplet (#9957).

IssueRefinementLoop needs a backlog-wide read — ALL open issues, no label
filter — carrying enough projection (title/body/labels) to reason about
content, not just identity (that's already covered by the narrower
``list_open_issue_numbers``, #9905).

Mirrors the #9943 precedent (``list_issues_by_label`` gaining a ``labels``
projection): the adapter projects ``number,title,body,labels,updatedAt``
and maps labels to gh wire shape (``[{"name": ...}]``) on both the
typed-model and raw-payload parse paths; FakeGitHub mirrors the same shape
(fake-fidelity).

Pins:
- The adapter calls ``gh issue list --state open --limit 500 --json
  number,title,body,labels,updatedAt`` (no label filter).
- Labels ride along in gh wire shape, mapped on both parse paths.
- FakeGitHub returns the same wire shape and excludes closed issues.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_pr_manager


def _gh_payload(n: int) -> str:
    """Build a gh-shaped JSON array of *n* open-issue rows."""
    return json.dumps(
        [
            {
                "number": i,
                "title": f"issue {i}",
                "body": "",
                "updatedAt": "2026-07-01T00:00:00Z",
                "labels": [],
            }
            for i in range(1, n + 1)
        ]
    )


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
            "labels": [],
        },
    ]
)


class TestAdapterProjectsAllOpenIssues:
    @pytest.mark.asyncio
    async def test_gh_invocation_has_no_label_filter_and_limit_500(
        self, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        run_gh = AsyncMock(return_value=_GH_PAYLOAD)

        with patch.object(mgr, "_run_gh", run_gh):
            issues = await mgr.list_open_issues()

        assert run_gh.await_args is not None
        argv = run_gh.await_args.args
        assert "--label" not in argv
        assert "number,title,body,labels,updatedAt" in argv
        assert "--limit" in argv
        assert argv[argv.index("--limit") + 1] == "500"
        assert len(issues) == 2

    @pytest.mark.asyncio
    async def test_projection_includes_labels_and_maps_wire_shape(
        self, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        run_gh = AsyncMock(return_value=_GH_PAYLOAD)

        with patch.object(mgr, "_run_gh", run_gh):
            issues = await mgr.list_open_issues()

        assert issues[0]["labels"] == [
            {"name": "hitl-escalation"},
            {"name": "human-required"},
        ]
        assert issues[1]["labels"] == []
        assert issues[1]["number"] == 8
        assert issues[1]["title"] == "Fresh"
        assert issues[1]["body"] == "retry me"
        assert issues[1]["updated_at"] == "2026-07-02T00:00:00Z"

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
            issues = await mgr.list_open_issues()

        assert issues[0]["labels"] == [{"name": "human-required"}]


class TestFakeGitHubParity:
    @pytest.mark.asyncio
    async def test_fake_returns_wire_shape_labels_and_all_open_issues(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(7, "Stuck", "x", labels=["hitl-escalation", "human-required"])
        gh.add_issue(8, "Fresh", "y")
        gh.add_issue(9, "Done", "z")
        await gh.close_issue(9)

        issues = await gh.list_open_issues()

        assert [i["number"] for i in issues] == [7, 8]
        assert issues[0]["labels"] == [
            {"name": "hitl-escalation"},
            {"name": "human-required"},
        ]
        assert issues[1]["labels"] == []


class TestTruncationWarning:
    """No-silent-caps: exactly 500 rows must warn (pattern: epic_sweeper_loop,
    service_registry's fitness issue fetcher)."""

    @pytest.mark.asyncio
    async def test_exactly_500_rows_logs_truncation_warning(
        self, config, event_bus, caplog: pytest.LogCaptureFixture
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        run_gh = AsyncMock(return_value=_gh_payload(500))

        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
            patch.object(mgr, "_run_gh", run_gh),
        ):
            issues = await mgr.list_open_issues()

        assert len(issues) == 500
        assert any(
            "list_open_issues returned exactly 500 rows" in r.message
            for r in caplog.records
        ), f"Expected truncation warning; got: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_499_rows_does_not_log_truncation_warning(
        self, config, event_bus, caplog: pytest.LogCaptureFixture
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        run_gh = AsyncMock(return_value=_gh_payload(499))

        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
            patch.object(mgr, "_run_gh", run_gh),
        ):
            issues = await mgr.list_open_issues()

        assert len(issues) == 499
        assert not any(
            "list_open_issues returned exactly 500 rows" in r.message
            for r in caplog.records
        )
