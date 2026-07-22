"""PRManager.find_label_drift — detects cross-entity issue/PR drift.

See ADR-0088. Two drift kinds:
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


class TestFindLabelDriftEscalatedWithResolvingPR:
    """#10260: an issue escalated to ``hitl-escalation``/``diagnose-failed``
    with an open, CI-green resolving PR carries stale labels — surface it so
    ``LabelDriftWatcherLoop`` can clear them."""

    @pytest.mark.asyncio
    async def test_detects_escalated_issue_with_green_resolving_pr(
        self, config, event_bus
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps([{"number": 100, "labels": [], "body": "Fixes #42"}])
        issue_json = json.dumps(
            {"labels": [{"name": "hitl-escalation"}, {"name": "diagnose-failed"}]}
        )
        checks_json = json.dumps(
            [
                {"name": "Tests", "state": "SUCCESS"},
                {"name": "Lint", "state": "SUCCESS"},
            ]
        )

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].kind == "escalated_with_resolving_pr"
        assert drift[0].issue == 42
        assert drift[0].pr == 100
        assert "hitl-escalation" in drift[0].issue_label
        assert "diagnose-failed" in drift[0].issue_label

    @pytest.mark.asyncio
    async def test_not_detected_when_ci_failing(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps([{"number": 100, "labels": [], "body": "Fixes #42"}])
        issue_json = json.dumps({"labels": [{"name": "hitl-escalation"}]})
        checks_json = json.dumps([{"name": "Tests", "state": "FAILURE"}])

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_when_no_checks_registered(
        self, config, event_bus
    ) -> None:
        """Empty checks list must NOT read as a green verdict (no CI yet)."""
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps([{"number": 100, "labels": [], "body": "Fixes #42"}])
        issue_json = json.dumps({"labels": [{"name": "hitl-escalation"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): json.dumps([]),
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_without_escalation_labels(
        self, config, event_bus
    ) -> None:
        """A green resolving PR on a NON-escalated, aligned issue is not this
        kind — falls through to the existing classification (no drift)."""
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps(
            [
                {
                    "number": 100,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "Fixes #42",
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-review"}]})
        checks_json = json.dumps([{"name": "Tests", "state": "SUCCESS"}])

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_takes_priority_over_pre_pr_stage_kind(
        self, config, event_bus
    ) -> None:
        """When BOTH an escalation label and a pre-PR-stage PR label are
        present, the more specific escalated_with_resolving_pr kind wins."""
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps(
            [
                {
                    "number": 100,
                    "labels": [{"name": "hydraflow-ready"}],
                    "body": "Fixes #42",
                }
            ]
        )
        issue_json = json.dumps(
            {"labels": [{"name": "hitl-escalation"}, {"name": "diagnose-failed"}]}
        )
        checks_json = json.dumps([{"name": "Tests", "state": "SUCCESS"}])

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].kind == "escalated_with_resolving_pr"

    @pytest.mark.asyncio
    async def test_not_detected_when_resolving_pr_is_draft(
        self, config, event_bus
    ) -> None:
        """#10260 review: a draft PR is not a reliable "this issue is
        resolved" signal even with green CI — mirrors the same guard on
        ``find_open_resolving_pr``. A stale escalation must not be cleared
        against a not-ready-for-review PR."""
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps(
            [{"number": 100, "labels": [], "body": "Fixes #42", "isDraft": True}]
        )
        issue_json = json.dumps(
            {"labels": [{"name": "hitl-escalation"}, {"name": "diagnose-failed"}]}
        )
        checks_json = json.dumps([{"name": "Tests", "state": "SUCCESS"}])

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_not_detected_for_bare_hitl_escalation_without_diagnose_failed(
        self, config, event_bus
    ) -> None:
        """#10260 review: many OTHER loops (corpus_learning_loop,
        trust_fleet_sanity_loop, wiki_rot_detector_loop, ...) file bare
        ``hitl-escalation`` + their own ``-stuck`` label with no pipeline
        label backing it. Clearing ``hitl-escalation`` for those would
        orphan the issue — those loops don't re-file until the operator
        closes the escalation. Only the diagnostic_loop pairing
        (``hitl-escalation`` + ``diagnose-failed``) may be cleared this way."""
        mgr = make_pr_manager(config, event_bus)
        prs_json = json.dumps([{"number": 100, "labels": [], "body": "Fixes #42"}])
        issue_json = json.dumps(
            {"labels": [{"name": "hitl-escalation"}, {"name": "corpus-learning-stuck"}]}
        )
        checks_json = json.dumps([{"name": "Tests", "state": "SUCCESS"}])

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("pr", "view"): _commits_json(1),
                        ("issue", "view"): issue_json,
                        ("pr", "checks"): checks_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []
