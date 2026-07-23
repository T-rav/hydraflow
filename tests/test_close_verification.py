"""Tests for the close-verification controller (#10358).

The G3 actuator: a post-merge observer that reopens + re-triages an issue a
merged PR closed without a fix delta (the #10223 false-close signature),
reusing the P10.7 classifier and honouring the same ``Skip-Regression:``
opt-out. Default-OFF and fully inert until ``close_verification_enabled``.

Exercised through ``FakeGitHub`` (a real ``PRPort``) — no live gh.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from close_verification import reconcile_false_close
from config import HydraFlowConfig
from events import EventBus, EventType
from mockworld.fakes.fake_github import FakeGitHub
from ports import PRPort


def _cfg(tmp_path: Path, *, enabled: bool) -> HydraFlowConfig:
    return HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        close_verification_enabled=enabled,
    )


def _seed_merged_close(
    gh: FakeGitHub,
    *,
    issue_number: int = 500,
    pr_number: int = 10_500,
    diff_names: list[str],
    message: str,
) -> None:
    """Seed a closed issue plus the merged PR that closed it."""
    gh.add_issue(issue_number, "Broken thing", "body", labels=["hydraflow-fixed"])
    gh._issues[issue_number].state = "closed"
    gh.add_pr(
        number=pr_number, issue_number=issue_number, branch="fix/500", merged=True
    )
    gh.set_pr_diff_names(pr_number, diff_names)
    gh.set_pr_commit_messages(pr_number, message)


async def test_delta_less_close_is_reopened_and_retriaged_when_enabled(
    tmp_path: Path,
) -> None:
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["docs/notes.md"],
        message="chore: tidy up\n\nCloses #500",
    )

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=True),
        prs=gh,
        issue_number=500,
        pr_number=10_500,
    )

    assert result.actuated is True
    assert result.reason == "reopened"
    assert gh._issues[500].state == "open"
    # Re-triaged onto the canonical find-label re-entry TriagePhase polls.
    assert gh._issues[500].labels == ["hydraflow-find"]
    # An explanatory comment lands on the reopened issue.
    assert any(n == 500 for n, _ in gh._comments)


async def test_source_delta_close_is_left_untouched(tmp_path: Path) -> None:
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["src/thing.py", "tests/test_thing.py"],
        message="fix: real bug\n\nCloses #500",
    )

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=True),
        prs=gh,
        issue_number=500,
        pr_number=10_500,
    )

    assert result.actuated is False
    assert result.reason == "fix-delta-present"
    assert gh._issues[500].state == "closed"
    assert gh._issues[500].labels == ["hydraflow-fixed"]


async def test_regression_delta_close_is_left_untouched(tmp_path: Path) -> None:
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["tests/regressions/test_issue_500.py"],
        message="test: pin the bug\n\nCloses #500",
    )

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=True),
        prs=gh,
        issue_number=500,
        pr_number=10_500,
    )

    assert result.actuated is False
    assert result.reason == "fix-delta-present"
    assert gh._issues[500].state == "closed"


async def test_skip_regression_close_is_left_untouched(tmp_path: Path) -> None:
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["docs/notes.md"],
        message="docs: clarify\n\nCloses #500\n\nSkip-Regression: fix shipped in #900",
    )

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=True),
        prs=gh,
        issue_number=500,
        pr_number=10_500,
    )

    assert result.actuated is False
    assert result.reason == "skip-regression"
    assert gh._issues[500].state == "closed"


async def test_disabled_flag_is_fully_inert(tmp_path: Path) -> None:
    """Flag OFF: no reopen, and — critically — no port calls at all."""
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["docs/notes.md"],
        message="chore: tidy up\n\nCloses #500",
    )

    # A spy PRPort proves the OFF path never touches GitHub.
    spy: PRPort = AsyncMock(spec=PRPort)

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=False),
        prs=spy,
        issue_number=500,
        pr_number=10_500,
    )

    assert result.actuated is False
    assert result.reason == "disabled"
    spy.get_pr_diff_names.assert_not_awaited()
    spy.reopen_issue.assert_not_awaited()
    spy.get_pr_commit_messages.assert_not_awaited()


async def test_actuation_publishes_system_alert(tmp_path: Path) -> None:
    gh = FakeGitHub()
    _seed_merged_close(
        gh,
        diff_names=["docs/notes.md"],
        message="chore: tidy up\n\nCloses #500",
    )
    bus = EventBus()
    queue = bus.subscribe()

    result = await reconcile_false_close(
        config=_cfg(tmp_path, enabled=True),
        prs=gh,
        issue_number=500,
        pr_number=10_500,
        bus=bus,
    )

    assert result.actuated is True
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    alerts = [e for e in events if e.type is EventType.SYSTEM_ALERT]
    assert alerts, "expected a SYSTEM_ALERT for the reopen"
    assert alerts[0].data["source"] == "close_verification"
    assert alerts[0].data["issue"] == 500
