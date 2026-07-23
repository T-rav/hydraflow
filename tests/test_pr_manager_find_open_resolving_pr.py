"""PRManager.find_open_resolving_pr — #10260.

Locates the open PR (if any) that resolves a given issue via a
``Fixes/Closes/Resolves #N`` body link. Used by the label/dispatch
reconciliation path so a stale escalation label never re-triggers a new
auto-agent attempt once a linked PR is already open.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import make_pr_manager


@pytest.mark.asyncio
async def test_finds_matching_open_pr(config, event_bus) -> None:
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps([{"number": 100, "body": "## Summary\n\nFixes #42.\n"}])

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result == 100


@pytest.mark.asyncio
async def test_returns_none_when_no_pr_matches(config, event_bus) -> None:
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps([{"number": 100, "body": "Fixes #99"}])

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_open_prs(config, event_bus) -> None:
    mgr = make_pr_manager(config, event_bus)

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=json.dumps([])),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["Fixes", "fixes", "Closes", "Resolves", "FIXES"])
async def test_recognizes_every_auto_close_keyword(
    keyword: str, config, event_bus
) -> None:
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps([{"number": 500, "body": f"## Summary\n\n{keyword} #42.\n"}])

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result == 500, f"Keyword {keyword!r} should be detected as a resolving link"


@pytest.mark.asyncio
async def test_picks_matching_pr_among_several(config, event_bus) -> None:
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps(
        [
            {"number": 100, "body": "Fixes #7"},
            {"number": 200, "body": "Fixes #42"},
            {"number": 300, "body": "no link here"},
        ]
    )

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result == 200


@pytest.mark.asyncio
async def test_gh_query_scoped_to_open_prs(config, event_bus) -> None:
    """The bulk ``pr list`` must request ``--state open`` — merged/closed
    PRs referencing the issue must never suppress a fresh escalation."""
    mgr = make_pr_manager(config, event_bus)
    calls: list[tuple[str, ...]] = []

    async def _record(*args, **kwargs):
        calls.append(args)
        return json.dumps([])

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(side_effect=_record),
    ):
        await mgr.find_open_resolving_pr(42)

    assert calls
    assert "open" in calls[0]


@pytest.mark.asyncio
async def test_finds_target_issue_when_not_the_first_link_in_body(
    config, event_bus
) -> None:
    """A body can carry more than one Fixes/Closes/Resolves link (e.g. an
    epic PR resolving several issues) — the target issue's link must be
    detected even when it isn't the first match in the body (#10260
    review)."""
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps(
        [{"number": 100, "body": "Closes #999.\n\nAlso fixes #42 in this PR."}]
    )

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result == 100


@pytest.mark.asyncio
async def test_ignores_draft_pr(config, event_bus) -> None:
    """A draft PR is not a reliable "this issue is resolved" signal even
    with a matching Fixes link — the author explicitly marked it not ready
    (#10260 review)."""
    mgr = make_pr_manager(config, event_bus)
    prs_json = json.dumps([{"number": 100, "body": "Fixes #42", "isDraft": True}])

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=prs_json),
    ):
        result = await mgr.find_open_resolving_pr(42)

    assert result is None
