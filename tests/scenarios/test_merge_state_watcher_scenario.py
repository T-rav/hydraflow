"""Sandbox-e2e scenario for MergeStateWatcherLoop (advisor-rxi).

Minimal ticks (Pattern B — direct instantiation):

* ``test_conflicting_pr_gets_rebased`` — one conflicting PR with no
  skip-labels; ``update_pr_branch`` succeeds and the loop returns
  ``checked=1, rebased=1``.
* ``test_no_conflicting_prs_returns_zero_counts`` — empty conflict list;
  all counters zero.
* ``TestApprovalRecordScenario`` — CH-2 (#9730): the loop tick reconciles a
  freshly merged PR into a hash-chained approval record (fake gh transport
  at the subprocess boundary), and a second tick dedups.

Pattern B is required because ``run_with_loops`` always forces
``ports["github"] = world._github`` (FakeGitHub), which does not implement
``list_conflicting_prs``.  Direct instantiation avoids that override.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import subprocess_util
from approval_records import ApprovalRecordReconciler
from audit_chain import AuditChain
from base_background_loop import LoopDeps
from events import EventBus
from merge_state_watcher import ConflictingPR
from merge_state_watcher_loop import MergeStateWatcherLoop
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario_loops


def _stub_reconciler():
    reconciler = MagicMock()
    reconciler.reconcile = AsyncMock(return_value={"merged_seen": 0, "recorded": 0})
    return reconciler


def _make_loop(tmp_path, fake_prs, *, config=None, reconciler=None):
    """Instantiate MergeStateWatcherLoop with a controlled fake PRPort."""
    if config is None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = EventBus()
    stop_event = asyncio.Event()
    stop_event.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    return MergeStateWatcherLoop(
        config=config,
        prs=fake_prs,
        deps=deps,
        approval_reconciler=(
            reconciler if reconciler is not None else _stub_reconciler()
        ),
    )


class TestMergeStateWatcherScenario:
    """advisor-rxi — sandbox-e2e for MergeStateWatcherLoop."""

    async def test_conflicting_pr_gets_rebased(self, tmp_path) -> None:
        """One conflicting PR with no skip-labels -> update_pr_branch called, rebased=1."""
        fake_prs = MagicMock()
        fake_prs.list_conflicting_prs = AsyncMock(
            return_value=[ConflictingPR(number=77, branch="feat/thing", labels=[])]
        )
        fake_prs.update_pr_branch = AsyncMock(return_value=True)
        # After update_pr_branch succeeds, the loop checks mergeability.
        # Returning True means the conflict is resolved -> "rebased" path taken.
        fake_prs.get_pr_mergeable = AsyncMock(return_value=True)
        fake_prs.add_pr_labels = AsyncMock(return_value=None)

        loop = _make_loop(tmp_path, fake_prs)
        result = await loop._do_work()

        assert result is not None, result
        assert result["checked"] == 1
        assert result["rebased"] == 1
        assert result["escalated"] == 0
        fake_prs.update_pr_branch.assert_awaited_once_with(77)

    async def test_no_conflicting_prs_returns_zero_counts(self, tmp_path) -> None:
        """No conflicting PRs -> all counters zero, update_pr_branch not called."""
        fake_prs = MagicMock()
        fake_prs.list_conflicting_prs = AsyncMock(return_value=[])
        fake_prs.update_pr_branch = AsyncMock(return_value=True)

        loop = _make_loop(tmp_path, fake_prs)
        result = await loop._do_work()

        assert result is not None, result
        assert result["checked"] == 0
        assert result["rebased"] == 0
        fake_prs.update_pr_branch.assert_not_awaited()


class TestApprovalRecordScenario:
    """CH-2 (#9730) — merged-PR approval records ride the loop tick."""

    @staticmethod
    def _fake_gh(monkeypatch, *, merged, details, login="hydra-ops-bot"):
        """Fake gh transport at the subprocess boundary (definition site)."""
        calls: list[tuple[str, ...]] = []

        async def _run(*cmd: str, **_kwargs) -> str:
            calls.append(cmd)
            if cmd[:3] == ("gh", "pr", "list"):
                return json.dumps(merged)
            if cmd[:3] == ("gh", "api", "user"):
                return login + "\n"
            if cmd[:3] == ("gh", "pr", "view"):
                return json.dumps(details[int(cmd[3])])
            raise AssertionError(f"unexpected gh call: {cmd}")

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
        return calls

    async def test_merged_pr_reconciled_into_chained_record_then_dedups(
        self, tmp_path, monkeypatch
    ) -> None:
        """Tick 1 records the merged PR (chained, role-classified);
        tick 2 is a no-op (read-back dedup)."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        detail = {
            "number": 501,
            "title": "feat: widget",
            "url": "https://github.com/test-org/test-repo/pull/501",
            "author": {"login": "agent-author", "is_bot": False},
            "mergedBy": {"login": "T-rav", "is_bot": False},
            "baseRefName": "staging",
            "headRefName": "worktree-issue-501",
            "headRefOid": "a" * 40,
            "mergeCommit": {"oid": "b" * 40},
            "mergedAt": "2026-07-08T12:00:00Z",
            "reviewDecision": "APPROVED",
            "reviews": [
                {
                    "author": {"login": "reviewer-1"},
                    "state": "APPROVED",
                    "submittedAt": "2026-07-08T11:00:00Z",
                }
            ],
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "Quality",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://github.com/t/actions/runs/1/job/2",
                }
            ],
        }
        self._fake_gh(
            monkeypatch,
            merged=[{"number": 501, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={501: detail},
        )
        fake_prs = MagicMock()
        fake_prs.list_conflicting_prs = AsyncMock(return_value=[])
        loop = _make_loop(
            tmp_path,
            fake_prs,
            config=config,
            reconciler=ApprovalRecordReconciler(config),
        )

        first = await loop._do_work()
        assert first is not None, first
        assert first["approvals"] == {
            "merged_seen": 1,
            "recorded": 1,
            "capture_gap_risk": False,
            "record_failures": 0,
        }

        records = [
            json.loads(line)
            for line in config.approval_records_path.read_text().splitlines()
        ]
        assert len(records) == 1
        assert records[0]["pr_number"] == 501
        assert records[0]["approver_identity"] == "T-rav"
        assert records[0]["role"] == "operator"
        assert records[0]["role_separated"] is True
        assert records[0]["evidence"]["ci_checks"][0]["name"] == "Quality"
        assert AuditChain(config.approval_records_path).verify().ok

        second = await loop._do_work()
        assert second is not None, second
        assert second["approvals"] == {
            "merged_seen": 1,
            "recorded": 0,
            "capture_gap_risk": False,
            "record_failures": 0,
        }
        assert len(config.approval_records_path.read_text().splitlines()) == 1
