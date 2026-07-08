"""Shared escalation reconciler: closed-escalation state clearing + open-
escalation re-verification against the current tick's detections.

Closing a stuck escalation is today the ONLY reset mechanism, and it is
human-gated — #9618 sat six days as a dead letter while later PRs may have
fixed the gap. `reconcile_open` closes any open escalation whose subject is
absent from the loop's currently-detected set, so escalations track reality
instead of waiting for a human.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from dedup_store import DedupStore
from escalation_reconcile import EscalationReconciler


@pytest.fixture
def env(tmp_path: Path):
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = DedupStore("esc_test", tmp_path / "dedup" / "esc_test.json")
    cleared: list[str] = []
    rec = EscalationReconciler(
        prs=prs,
        dedup=dedup,
        key_prefix="fake_coverage_auditor",
        stuck_label="hydraflow-fake-coverage-stuck",
        clear_attempts=cleared.append,
    )
    return rec, prs, dedup, cleared


def _issue(number: int, title: str) -> dict:
    return {"number": number, "title": title, "body": "", "updated_at": ""}


class TestReconcileClosed:
    @pytest.mark.asyncio
    async def test_clears_key_and_attempts_on_matching_closed_title(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(
                9618,
                "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
            )
        ]
        await rec.reconcile_closed()
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_keeps_keys_without_matching_closed_title(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(1, "HITL: fake coverage gap FakeDocker:test-helper x")
        ]
        await rec.reconcile_closed()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_ignores_foreign_prefixes(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"other_loop:FakeGitHub:adapter-surface"})
        prs.list_closed_issues_by_label.return_value = [
            _issue(1, "HITL: fake coverage gap FakeGitHub:adapter-surface x")
        ]
        await rec.reconcile_closed()
        assert dedup.get() == {"other_loop:FakeGitHub:adapter-surface"}
        assert cleared == []


class TestReconcileOpen:
    @pytest.mark.asyncio
    async def test_closes_escalation_when_subject_no_longer_detected(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [
            _issue(
                9618,
                "HITL: fake coverage gap FakeGitHub:adapter-surface unresolved after 3",
            )
        ]
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 1
        prs.post_comment.assert_awaited_once()
        assert "no longer detected" in prs.post_comment.await_args.args[1]
        prs.close_issue.assert_awaited_once_with(9618)
        assert dedup.get() == set()
        assert cleared == ["FakeGitHub:adapter-surface"]

    @pytest.mark.asyncio
    async def test_keeps_escalation_while_subject_still_detected(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [
            _issue(9618, "HITL: fake coverage gap FakeGitHub:adapter-surface x")
        ]
        closed = await rec.reconcile_open(
            active_subjects={"FakeGitHub:adapter-surface"}
        )
        assert closed == 0
        prs.close_issue.assert_not_awaited()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}

    @pytest.mark.asyncio
    async def test_none_active_subjects_skips_entirely(self, env) -> None:
        """Detection failed/partial this tick — closing on incomplete data
        would kill real escalations and reset their attempt budgets."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        closed = await rec.reconcile_open(active_subjects=None)
        assert closed == 0
        prs.list_issues_by_label.assert_not_awaited()
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}

    @pytest.mark.asyncio
    async def test_no_matching_open_issue_leaves_state_alone(self, env) -> None:
        """Close-then-clear: without an actual close, the dedup key is left
        for reconcile_closed — some loops share the store with first-pass
        rollup dedup, and clearing without a close could re-file those."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = []
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 0
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []

    @pytest.mark.asyncio
    async def test_failed_close_retains_key_and_attempts(self, env) -> None:
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.return_value = [
            _issue(9618, "HITL: fake coverage gap FakeGitHub:adapter-surface x")
        ]
        prs.close_issue.side_effect = RuntimeError("gh down mid-close")
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 0
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
        assert cleared == []  # retry next tick with budget intact

    @pytest.mark.asyncio
    async def test_port_error_is_swallowed(self, env) -> None:
        """A gh outage must not crash the loop cycle — skip, retry next tick."""
        rec, prs, dedup, cleared = env
        dedup.set_all({"fake_coverage_auditor:FakeGitHub:adapter-surface"})
        prs.list_issues_by_label.side_effect = RuntimeError("gh down")
        closed = await rec.reconcile_open(active_subjects=set())
        assert closed == 0
        assert dedup.get() == {"fake_coverage_auditor:FakeGitHub:adapter-surface"}
