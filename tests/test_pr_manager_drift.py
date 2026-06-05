"""PRManager.find_label_drift — detects cross-entity issue/PR drift.

See ADR-0056. Two drift kinds:
- ``pr_ahead_of_issue``: issue at ready/plan, PR at review with commits
- ``pr_at_pre_pr_stage``: PR labelled ready/plan but has commits

The commit count is fetched per Fixes-matched PR via ``gh pr view --json
commits`` (not the bulk ``pr list``, which would expand the authors connection
and exceed GitHub's GraphQL node ceiling), so these tests script a
``("pr", "view")`` response for matched PRs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import make_pr_manager


def _gh_responder(mapping: dict[tuple[str, ...], str]):
    """Return an AsyncMock side_effect that dispatches by tuple of cmd args.

    ``mapping`` keys are partial-match tuples (e.g. ("pr", "list")) — the
    first key whose elements all appear in the call's positional args wins.
    """

    async def _side_effect(*args, **kwargs):
        for key, response in mapping.items():
            if all(part in args for part in key):
                return response
        raise AssertionError(f"unexpected gh call: {args}")

    return _side_effect


def _commits_json(n: int) -> str:
    return json.dumps({"commits": [{"oid": str(i)} for i in range(n)]})


class TestFindLabelDrift:
    @pytest.mark.asyncio
    async def test_detects_issue_at_ready_pr_at_review(self, config, event_bus) -> None:
        """Issue labelled hydraflow-ready while its PR is at hydraflow-review
        with commits → kind=pr_ahead_of_issue."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 100,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "## Summary\n\nFixes #42.\n",
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-ready"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(2),
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].issue == 42
        assert drift[0].pr == 100
        assert drift[0].kind == "pr_ahead_of_issue"
        assert drift[0].issue_label == "hydraflow-ready"
        assert drift[0].pr_label == "hydraflow-review"
        assert drift[0].pr_commits == 2

    @pytest.mark.asyncio
    async def test_detects_pr_at_ready_with_commits(self, config, event_bus) -> None:
        """PR labelled hydraflow-ready but has commits → kind=pr_at_pre_pr_stage."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 200,
                    "labels": [{"name": "hydraflow-ready"}],
                    "body": "Fixes #99",
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-review"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(3),
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].pr == 200
        assert drift[0].kind == "pr_at_pre_pr_stage"
        assert drift[0].pr_commits == 3

    @pytest.mark.asyncio
    async def test_no_drift_when_aligned(self, config, event_bus) -> None:
        """Issue and PR both at hydraflow-review → empty list."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 300,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "Fixes #7",
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-review"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_skips_prs_without_fixes_link(self, config, event_bus) -> None:
        """PR body without 'Fixes #N' is skipped — no linked issue to check."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 400,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "no fixes link here",
                }
            ]
        )

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(side_effect=_gh_responder({("pr", "list"): prs_json})),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_bulk_pr_list_does_not_request_commits(
        self, config, event_bus
    ) -> None:
        """The bulk ``pr list`` must not request ``commits`` — that field
        expands each commit's authors connection and exceeds GitHub's GraphQL
        500k-node ceiling at --limit 200 (the original failure)."""
        mgr = make_pr_manager(config, event_bus)
        calls: list[tuple[str, ...]] = []

        async def _record(*args, **kwargs):
            calls.append(args)
            if "list" in args:
                return json.dumps([])
            return json.dumps({"labels": []})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(side_effect=_record),
        ):
            await mgr.find_label_drift()

        pr_list_calls = [a for a in calls if "list" in a]
        assert pr_list_calls
        for call_args in pr_list_calls:
            assert "commits" not in ",".join(call_args)


class TestFindLabelDriftAutoCloseKeywords:
    """``find_label_drift`` must recognize every auto-close keyword GitHub does
    (``Fixes``, ``Closes``, ``Resolves`` — case insensitive). Regex previously
    matched only ``[Ff]ixes`` so PRs using ``Closes``/``Resolves`` were
    silently skipped. See #8725.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "keyword",
        ["Fixes", "fixes", "Closes", "closes", "Resolves", "resolves", "FIXES"],
    )
    async def test_detects_each_auto_close_keyword(
        self, keyword: str, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 500,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": f"## Summary\n\n{keyword} #42.\n",
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-ready"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1, (
            f"Keyword {keyword!r} should be detected as an auto-close link"
        )
        assert drift[0].issue == 42
        assert drift[0].pr == 500
