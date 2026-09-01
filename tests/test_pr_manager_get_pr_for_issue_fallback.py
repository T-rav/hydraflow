"""`get_pr_for_issue` falls back to what a PR declares (#11986).

The branch-name lookup builds `agent/issue-{N}` and asks GitHub for a PR with
that head. That pattern is a convention, not a rule: any manually opened fix —
`feat/{N}-slug`, `fix/{N}-thing` — is invisible to it.

Its only consumer is `changelog.py`, which writes the entry with the returned
number. A silent `0` in a generated changelog is worse than a missing entry,
because it reads as an answer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import make_pr_manager  # noqa: E402


def _pr(number: int, *, title: str = "", body: str = "", updated: str = "") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "updatedAt": updated or "2026-09-01T00:00:00Z",
    }


class TestTheBranchNameLookupStillWins:
    @pytest.mark.asyncio
    async def test_an_agent_branch_pr_is_found_without_the_fallback(
        self, config, event_bus
    ) -> None:
        """The existing path is unchanged; the fallback is only a fallback."""
        mgr = make_pr_manager(config, event_bus)

        with patch.object(
            mgr, "_gh_json_query", new=AsyncMock(return_value=[{"number": 77}])
        ) as query:
            assert await mgr.get_pr_for_issue(42) == 77

        # One call: it returned on the first state searched and never fell back.
        assert query.await_count == 1


class TestADifferentlyNamedBranchIsStillFound:
    @pytest.mark.parametrize(
        ("pr", "expected"),
        [
            pytest.param(
                _pr(101, body="## Summary\n\nCloses #42.\n"), 101, id="body-declares"
            ),
            pytest.param(
                _pr(102, title="fix(x): thing — Fixes #42", body=""),
                102,
                id="title-declares",
            ),
            # The two that must NOT match are the point of the set: a bare
            # mention claiming the issue is exactly how a changelog attributes
            # a fix to the wrong PR, and it is the decoy that keeps the two
            # positives above from passing against a matcher that says yes to
            # everything.
            pytest.param(
                _pr(103, body="Related to #42, but does not fix it."),
                0,
                id="bare-mention-is-not-a-declaration",
            ),
            pytest.param(_pr(104, body="Closes #99"), 0, id="a-different-issue"),
        ],
    )
    @pytest.mark.asyncio
    async def test_only_a_real_declaration_of_this_issue_matches(
        self, config, event_bus, pr: dict, expected: int
    ) -> None:
        mgr = make_pr_manager(config, event_bus)
        calls = [[], [], [pr]]

        with patch.object(mgr, "_gh_json_query", new=AsyncMock(side_effect=calls)):
            assert await mgr.get_pr_for_issue(42) == expected

    @pytest.mark.asyncio
    async def test_the_most_recently_updated_declaration_wins(
        self, config, event_bus
    ) -> None:
        """An epic PR and the PR that did the work can both declare an issue."""
        mgr = make_pr_manager(config, event_bus)
        calls = [
            [],
            [],
            [
                _pr(200, body="Closes #42", updated="2026-08-01T00:00:00Z"),
                _pr(201, body="Closes #42", updated="2026-09-01T00:00:00Z"),
            ],
        ]

        with patch.object(mgr, "_gh_json_query", new=AsyncMock(side_effect=calls)):
            assert await mgr.get_pr_for_issue(42) == 201


class TestTheFallbackFailsQuietly:
    @pytest.mark.asyncio
    async def test_a_malformed_response_returns_zero_rather_than_raising(
        self, config, event_bus
    ) -> None:
        """This runs inside changelog generation; it must never be the thing
        that breaks a release."""
        mgr = make_pr_manager(config, event_bus)

        with patch.object(
            mgr, "_gh_json_query", new=AsyncMock(side_effect=[[], [], "not a list"])
        ):
            assert await mgr.get_pr_for_issue(42) == 0

    @pytest.mark.asyncio
    async def test_an_entry_with_no_number_is_skipped(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        calls = [[], [], [{"body": "Closes #42"}, _pr(105, body="Closes #42")]]

        with patch.object(mgr, "_gh_json_query", new=AsyncMock(side_effect=calls)):
            assert await mgr.get_pr_for_issue(42) == 105

    @pytest.mark.asyncio
    async def test_dry_run_still_short_circuits(self, config, event_bus) -> None:
        config.dry_run = True
        mgr = make_pr_manager(config, event_bus)

        with patch.object(mgr, "_gh_json_query", new=AsyncMock()) as query:
            assert await mgr.get_pr_for_issue(42) == 0

        query.assert_not_awaited()
