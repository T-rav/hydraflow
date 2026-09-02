"""Regression: an issue's PR is found even off the `agent/issue-{N}` branch.

#11986. `PRManager.get_pr_for_issue` resolved a PR by constructing
`agent/issue-{N}` and querying for that head. The pattern is a convention, not
a rule — every manually opened fix uses something else — and the branch lookup
had no fallback.

The consumer is `changelog.py`, so the symptom was a real fix appearing in a
generated changelog with **PR number 0**. That is worse than a missing entry,
because a 0 reads as an answer rather than as a gap.

The detailed behaviour lives in
`tests/test_pr_manager_get_pr_for_issue_fallback.py`; this pins the one shape
the defect actually took.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import make_pr_manager  # noqa: E402


@pytest.mark.asyncio
async def test_a_manually_branched_fix_is_still_attributed(
    config, event_bus
) -> None:
    mgr = make_pr_manager(config, event_bus)

    # Both branch-name states miss it: the PR was opened from `feat/42-thing`.
    # It declares the issue in its body, which is the evidence that survives.
    responses = [
        [],
        [],
        [
            {
                "number": 4242,
                "title": "feat(x): the thing",
                "body": "## Summary\n\nCloses #42.\n",
                "updatedAt": "2026-09-01T00:00:00Z",
            }
        ],
    ]

    with patch.object(mgr, "_gh_json_query", new=AsyncMock(side_effect=responses)):
        found = await mgr.get_pr_for_issue(42)

    assert found == 4242, (
        "a fix opened from a non-agent branch resolved to PR 0, which "
        "changelog.py then wrote into the release notes as an answer"
    )
