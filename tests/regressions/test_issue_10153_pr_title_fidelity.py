"""Regression pin for issue #10153 — FakeGitHub PR-title format fidelity.

``FakeGitHub.expected_pr_title`` once returned ``[#<n>] <title>`` while the
real ``PRManager.expected_pr_title`` returns ``Fixes #<n>: <title>`` (truncated
to 70 chars). FakeGitHub is cast to ``PRPort`` in the sandbox harness
(``mockworld/sandbox_main.py``), so the divergence was live-reachable — a fake
that lied about the real title format, letting wrong-format PR titles slip past
MockWorld/sandbox tests. The fix delegates the fake to the real formatter so the
two can never drift apart again.

This pin fails if anyone reintroduces a divergent fake format.
"""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from pr_manager import PRManager


@pytest.mark.parametrize(
    ("issue_number", "issue_title"),
    [
        (524, "Improve caching layer performance"),
        (1, "Fix bug"),
        (0, ""),
        (77, "Fix the gizmo"),
        # Long title exercises PRManager's 70-char truncation branch.
        (99, "y" * 200),
    ],
)
def test_fake_expected_pr_title_matches_real(
    issue_number: int, issue_title: str
) -> None:
    """The fake's PR title must be byte-identical to the real PRManager's."""
    assert FakeGitHub.expected_pr_title(issue_number, issue_title) == (
        PRManager.expected_pr_title(issue_number, issue_title)
    )


def test_fake_expected_pr_title_uses_fixes_prefix_not_bracket() -> None:
    """Guard the specific regression: never revert to the ``[#n] title`` shape."""
    title = FakeGitHub.expected_pr_title(524, "Improve caching layer performance")
    assert title == "Fixes #524: Improve caching layer performance"
    assert not title.startswith("[#"), (
        f"FakeGitHub.expected_pr_title regressed to bracket format: {title!r}"
    )
