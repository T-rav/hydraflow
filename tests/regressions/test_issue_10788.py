"""Regression: timeline diff stats in pr_created / merge_update events (#10788).

The operator timeline renders commit sha, files-changed and ±lines when the
``pr_created`` / ``merge_update`` WS payloads carry them. The frontend already
reads the keys defensively, so the backend contract is: ``PRManager`` does a
best-effort ``gh pr view`` read at each of the four emit sites and merges only
the keys GitHub reported — never fabricating zero-valued stats, never letting
a failed read block the event.

Pins:
* ``get_pr_diff_stats`` shape logic: full reply, mergeCommit-vs-headRefOid sha,
  raising read, dry-run, and null/malformed fields.
* All four emit sites carry the keys on success and OMIT them on a failed read.
* ``FakeGitHub`` mirrors the method for scenario fidelity.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventType
from models import PRDiffStats
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory, make_pr_manager

_DIFF_KEYS = {"commit_sha", "files_changed", "additions", "deletions"}

_FULL_REPLY = (
    '{"headRefOid":"headsha","mergeCommit":{"oid":"mergesha"},'
    '"additions":10,"deletions":2,"changedFiles":3}'
)


def _make_pm(*, dry_run: bool = False) -> Any:
    cfg = ConfigFactory.create(repo="owner/repo", dry_run=dry_run)
    bus = MagicMock()
    bus.publish = AsyncMock()
    return make_pr_manager(cfg, bus)


def _events(pm: Any, event_type: EventType) -> list[Any]:
    return [
        call.args[0]
        for call in pm._bus.publish.call_args_list
        if call.args and getattr(call.args[0], "type", None) == event_type
    ]


# --------------------------------------------------------------------------
# get_pr_diff_stats — shape logic (real method, stubbed _run_gh)
# --------------------------------------------------------------------------


class TestGetPrDiffStats:
    async def test_full_reply_yields_all_stats_with_merge_commit_sha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _reply(*_cmd: str, **_kw: Any) -> str:
            return _FULL_REPLY

        monkeypatch.setattr(pm, "_run_gh", _reply)

        stats = await pm.get_pr_diff_stats(101)
        assert stats == {
            # sha resolves to the merge commit when present, not the head sha.
            "commit_sha": "mergesha",
            "files_changed": 3,
            "additions": 10,
            "deletions": 2,
        }

    async def test_falls_back_to_head_ref_oid_without_merge_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _reply(*_cmd: str, **_kw: Any) -> str:
            # No mergeCommit yet (creation time) -> head sha is used.
            return (
                '{"headRefOid":"headsha","mergeCommit":null,'
                '"additions":1,"deletions":0,"changedFiles":1}'
            )

        monkeypatch.setattr(pm, "_run_gh", _reply)

        stats = await pm.get_pr_diff_stats(101)
        assert stats["commit_sha"] == "headsha"
        assert stats["files_changed"] == 1

    async def test_raising_read_yields_empty_and_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _boom(*_cmd: str, **_kw: Any) -> str:
            raise RuntimeError("gh exploded")

        monkeypatch.setattr(pm, "_run_gh", _boom)

        # Must not raise; returns an empty dict so callers merge a no-op.
        assert await pm.get_pr_diff_stats(101) == {}

    async def test_dry_run_yields_empty_without_calling_gh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm(dry_run=True)
        called = False

        async def _spy(*_cmd: str, **_kw: Any) -> str:
            nonlocal called
            called = True
            return _FULL_REPLY

        monkeypatch.setattr(pm, "_run_gh", _spy)

        assert await pm.get_pr_diff_stats(101) == {}
        assert called is False

    async def test_null_or_missing_fields_are_omitted_not_zeroed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _reply(*_cmd: str, **_kw: Any) -> str:
            # A degraded reply: every field null. No zero-valued stat may leak.
            return (
                '{"headRefOid":null,"mergeCommit":null,'
                '"additions":null,"deletions":null,"changedFiles":null}'
            )

        monkeypatch.setattr(pm, "_run_gh", _reply)

        assert await pm.get_pr_diff_stats(101) == {}


# --------------------------------------------------------------------------
# create_pr emit site
# --------------------------------------------------------------------------


class TestCreatePrEmit:
    async def test_pr_created_carries_diff_keys_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _create(*_a: Any, **_kw: Any) -> str:
            return "https://github.com/owner/repo/pull/55"

        monkeypatch.setattr(pm, "_run_with_body_file", _create)
        monkeypatch.setattr(
            pm,
            "get_pr_diff_stats",
            AsyncMock(
                return_value=PRDiffStats(
                    commit_sha="headsha", files_changed=4, additions=20, deletions=1
                )
            ),
        )

        await pm.create_pr(IssueFactory.create(number=42, title="t"), "agent/issue-42")

        data = _events(pm, EventType.PR_CREATED)[-1].data
        assert data["pr"] == 55
        assert data["commit_sha"] == "headsha"
        assert data["files_changed"] == 4
        assert data["additions"] == 20
        assert data["deletions"] == 1

    async def test_pr_created_omits_diff_keys_on_failed_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _create(*_a: Any, **_kw: Any) -> str:
            return "https://github.com/owner/repo/pull/55"

        monkeypatch.setattr(pm, "_run_with_body_file", _create)
        monkeypatch.setattr(pm, "get_pr_diff_stats", AsyncMock(return_value={}))

        await pm.create_pr(IssueFactory.create(number=42, title="t"), "agent/issue-42")

        data = _events(pm, EventType.PR_CREATED)[-1].data
        assert _DIFF_KEYS.isdisjoint(data.keys())
        # Base contract still intact.
        assert data["pr"] == 55
        assert data["issue"] == 42


# --------------------------------------------------------------------------
# merge_pr emit site
# --------------------------------------------------------------------------


class TestMergePrEmit:
    async def test_merge_update_carries_merge_commit_sha_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()
        monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
        monkeypatch.setattr(
            pm,
            "get_pr_title_and_body",
            AsyncMock(return_value=("Fixes #42: do it", "body")),
        )
        monkeypatch.setattr(
            pm,
            "get_pr_diff_stats",
            AsyncMock(
                return_value=PRDiffStats(
                    commit_sha="mergesha", files_changed=3, additions=10, deletions=2
                )
            ),
        )

        assert await pm.merge_pr(101) is True

        data = _events(pm, EventType.MERGE_UPDATE)[-1].data
        # sha is the (squash) merge commit, not the pre-merge head.
        assert data["commit_sha"] == "mergesha"
        assert data["files_changed"] == 3
        assert data["additions"] == 10
        assert data["deletions"] == 2
        assert data["status"] == "merged"

    async def test_merge_update_omits_diff_keys_on_failed_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()
        monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
        monkeypatch.setattr(
            pm,
            "get_pr_title_and_body",
            AsyncMock(return_value=("Fixes #42: do it", "body")),
        )
        monkeypatch.setattr(pm, "get_pr_diff_stats", AsyncMock(return_value={}))

        assert await pm.merge_pr(101) is True

        data = _events(pm, EventType.MERGE_UPDATE)[-1].data
        assert _DIFF_KEYS.isdisjoint(data.keys())
        assert data["status"] == "merged"


# --------------------------------------------------------------------------
# promotion emit sites (create_promotion_pr / merge_promotion_pr)
# --------------------------------------------------------------------------


class TestPromotionEmit:
    async def test_create_promotion_pr_carries_diff_keys_issue_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()

        async def _create(*_a: Any, **_kw: Any) -> str:
            return "https://github.com/owner/repo/pull/99"

        monkeypatch.setattr(pm, "_run_with_body_file", _create)
        monkeypatch.setattr(
            pm,
            "get_pr_diff_stats",
            AsyncMock(
                return_value=PRDiffStats(
                    commit_sha="headsha", files_changed=7, additions=30, deletions=4
                )
            ),
        )

        await pm.create_promotion_pr(
            rc_branch="rc/2026-04-17-1600", title="promote", body="b"
        )

        data = _events(pm, EventType.PR_CREATED)[-1].data
        assert data["pr"] == 99
        assert data["issue"] == 0
        assert data["files_changed"] == 7
        assert data["commit_sha"] == "headsha"

    async def test_merge_promotion_pr_carries_diff_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _make_pm()
        monkeypatch.setattr("pr_manager_promotion.run_subprocess", AsyncMock())
        monkeypatch.setattr(
            pm,
            "get_pr_diff_stats",
            AsyncMock(
                return_value=PRDiffStats(
                    commit_sha="mergesha", files_changed=3, additions=10, deletions=2
                )
            ),
        )

        assert await pm.merge_promotion_pr(99) is True

        data = _events(pm, EventType.MERGE_UPDATE)[-1].data
        assert data["commit_sha"] == "mergesha"
        assert data["files_changed"] == 3


# --------------------------------------------------------------------------
# FakeGitHub mirror
# --------------------------------------------------------------------------


class TestFakeGitHubDiffStats:
    async def test_default_stub_is_non_empty(self) -> None:
        from mockworld.fakes.fake_github import FakeGitHub

        stats = await FakeGitHub().get_pr_diff_stats(5)
        assert set(stats) == _DIFF_KEYS

    async def test_seeded_stats_are_returned(self) -> None:
        from mockworld.fakes.fake_github import FakeGitHub

        fg = FakeGitHub()
        fg.set_pr_diff_stats(
            5, PRDiffStats(commit_sha="zzz", files_changed=9, additions=1, deletions=1)
        )
        assert await fg.get_pr_diff_stats(5) == {
            "commit_sha": "zzz",
            "files_changed": 9,
            "additions": 1,
            "deletions": 1,
        }
