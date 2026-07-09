"""Unit tests for the CH-2 approval-record reconciler (#9730).

Covers the pure record-building logic (schema, role classification, role
separation), the read-back dedup, idempotency across ticks, chain integrity
of appended records, and outage behavior (errors propagate to the loop
cycle handler; partial progress is preserved and self-heals next tick).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import subprocess_util
from approval_records import (
    APPROVAL_RECORD_SCHEMA_VERSION,
    FACTORY_AUTONOMY_CLAUSE,
    RECORD_TYPE_BREAK_GLASS,
    ROLE_DELEGATED_BOT,
    ROLE_OPERATOR,
    ROLE_ORCHESTRATOR,
    ApprovalRecordReconciler,
)
from audit_chain import AuditChain
from tests.helpers import ConfigFactory

FACTORY_LOGIN = "hydra-ops-bot"
HUMAN_LOGIN = "T-rav"


def _detail(
    number: int = 101,
    *,
    author: str = "agent-author",
    approver: str | None = HUMAN_LOGIN,
    approver_is_bot: bool = False,
    base: str = "staging",
    head: str = "worktree-issue-101",
    head_sha: str = "a" * 40,
    merge_sha: str = "b" * 40,
    merged_at: str = "2026-07-08T12:00:00Z",
    review_decision: str = "APPROVED",
    reviews: list[dict[str, Any]] | None = None,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a ``gh pr view --json`` payload in the live-verified shape."""
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/test-org/test-repo/pull/{number}",
        "author": {"login": author, "is_bot": False, "name": ""},
        "mergedBy": (
            {"login": approver, "is_bot": approver_is_bot, "name": ""}
            if approver is not None
            else None
        ),
        "baseRefName": base,
        "headRefName": head,
        "headRefOid": head_sha,
        "mergeCommit": {"oid": merge_sha},
        "mergedAt": merged_at,
        "reviewDecision": review_decision,
        "reviews": reviews if reviews is not None else [],
        "statusCheckRollup": checks if checks is not None else [],
    }


class FakeGh:
    """Fake gh transport dispatching on the subprocess argv shape."""

    def __init__(
        self,
        *,
        merged: list[dict[str, Any]] | None = None,
        details: dict[int, Any] | None = None,
        login: str = FACTORY_LOGIN,
    ) -> None:
        self.merged = merged if merged is not None else []
        self.details = details if details is not None else {}
        self.login = login
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *cmd: str, **_kwargs: Any) -> str:
        self.calls.append(cmd)
        if cmd[:3] == ("gh", "pr", "list"):
            return json.dumps(self.merged)
        if cmd[:3] == ("gh", "api", "user"):
            return self.login + "\n"
        if cmd[:3] == ("gh", "pr", "view"):
            detail = self.details[int(cmd[3])]
            if isinstance(detail, Exception):
                raise detail
            return json.dumps(detail)
        raise AssertionError(f"unexpected gh call: {cmd}")

    def calls_starting(self, *prefix: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]


@pytest.fixture
def config(tmp_path):
    return ConfigFactory.create(repo_root=tmp_path / "repo")


def _install(monkeypatch, fake: FakeGh) -> None:
    monkeypatch.setattr(subprocess_util, "run_subprocess", fake)


def _read_records(config) -> list[dict[str, Any]]:
    path = config.approval_records_path
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestRecordShape:
    async def test_records_merged_pr_with_full_schema(
        self, config, monkeypatch
    ) -> None:
        """A newly merged PR produces one record carrying the CH-2 schema."""
        reviews = [
            {
                "author": {"login": "reviewer-1"},
                "state": "APPROVED",
                "submittedAt": "2026-07-08T11:00:00Z",
            }
        ]
        checks = [
            {
                "__typename": "CheckRun",
                "name": "Quality",
                "conclusion": "SUCCESS",
                "detailsUrl": "https://github.com/test/actions/runs/1/job/2",
                "status": "COMPLETED",
            },
            {
                "__typename": "StatusContext",
                "context": "legacy-ci",
                "state": "SUCCESS",
                "targetUrl": "https://ci.example/run/9",
            },
        ]
        fake = FakeGh(
            merged=[{"number": 101, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={101: _detail(101, reviews=reviews, checks=checks)},
        )
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"merged_seen": 1, "recorded": 1, "capture_gap_risk": False}
        records = _read_records(config)
        assert len(records) == 1
        rec = records[0]
        assert rec["schema"] == APPROVAL_RECORD_SCHEMA_VERSION
        assert rec["record_type"] == "approval"
        assert rec["repo"] == config.repo
        assert rec["pr_number"] == 101
        assert rec["base_branch"] == "staging"
        assert rec["head_branch"] == "worktree-issue-101"
        assert rec["head_sha"] == "a" * 40
        assert rec["merge_commit_sha"] == "b" * 40
        assert rec["merged_at"] == "2026-07-08T12:00:00Z"
        assert rec["timestamp"]  # reconcile-time ISO timestamp
        assert rec["author_identity"] == "agent-author"
        assert rec["approver_identity"] == HUMAN_LOGIN
        assert rec["role"] == ROLE_OPERATOR
        assert rec["role_separated"] is True
        assert rec["delegation_basis"] is None
        assert rec["evidence"]["review_decision"] == "APPROVED"
        assert rec["evidence"]["reviews"] == [
            {
                "author": "reviewer-1",
                "state": "APPROVED",
                "submitted_at": "2026-07-08T11:00:00Z",
            }
        ]
        assert rec["evidence"]["ci_checks"] == [
            {
                "name": "Quality",
                "conclusion": "SUCCESS",
                "run_url": "https://github.com/test/actions/runs/1/job/2",
            },
            {
                "name": "legacy-ci",
                "conclusion": "SUCCESS",
                "run_url": "https://ci.example/run/9",
            },
        ]

    async def test_records_are_hash_chained_and_verify(
        self, config, monkeypatch
    ) -> None:
        """Approval records ride the CH-1 chain: verify() is clean."""
        fake = FakeGh(
            merged=[
                {"number": 1, "mergedAt": "2026-07-08T10:00:00Z"},
                {"number": 2, "mergedAt": "2026-07-08T11:00:00Z"},
            ],
            details={1: _detail(1), 2: _detail(2)},
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        chain = AuditChain(config.approval_records_path)
        result = chain.verify()
        assert result.ok
        assert result.chained_records == 2

    async def test_missing_merged_by_records_empty_approver(
        self, config, monkeypatch
    ) -> None:
        """A deleted merging account yields approver='' and role_separated=False."""
        fake = FakeGh(
            merged=[{"number": 7, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={7: _detail(7, approver=None)},
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["approver_identity"] == ""
        assert rec["role"] == ROLE_OPERATOR
        assert rec["role_separated"] is False


class TestRoleClassification:
    async def test_human_merge_is_operator(self, config, monkeypatch) -> None:
        fake = FakeGh(
            merged=[{"number": 3, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={3: _detail(3, approver=HUMAN_LOGIN)},
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role"] == ROLE_OPERATOR
        assert rec["delegation_basis"] is None

    async def test_rc_promotion_is_orchestrator(self, config, monkeypatch) -> None:
        """rc/* → main merges are the StagingPromotionLoop's own promotions."""
        head = f"{config.rc_branch_prefix}2026-07-08-0400"
        fake = FakeGh(
            merged=[{"number": 4, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={
                4: _detail(
                    4,
                    approver=FACTORY_LOGIN,
                    base=config.main_branch,
                    head=head,
                )
            },
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role"] == ROLE_ORCHESTRATOR
        assert rec["delegation_basis"] is None

    async def test_human_merge_of_rc_promotion_is_operator(
        self, config, monkeypatch
    ) -> None:
        """Branch shape alone must not grant ``orchestrator`` (review finding).

        A human force-merging an rc/* promotion (blocked StagingPromotionLoop,
        terminal ``gh pr merge``) is recorded as the operator intervention it
        was — CH-3 consumers reading ``role`` must never mistake it for an
        automated promotion. ``head_branch`` still carries the rc/* origin.
        """
        head = f"{config.rc_branch_prefix}2026-07-08-0800"
        fake = FakeGh(
            merged=[{"number": 5, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={
                5: _detail(5, approver=HUMAN_LOGIN, base=config.main_branch, head=head)
            },
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role"] == ROLE_OPERATOR
        assert rec["delegation_basis"] is None
        assert rec["approver_identity"] == HUMAN_LOGIN
        assert rec["head_branch"] == head

    async def test_factory_identity_merge_is_delegated_bot_with_clause(
        self, config, monkeypatch
    ) -> None:
        """Bot-lane merges record WHO delegated and under which clause."""
        fake = FakeGh(
            merged=[{"number": 5, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={5: _detail(5, approver=FACTORY_LOGIN)},
            login=FACTORY_LOGIN,
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role"] == ROLE_DELEGATED_BOT
        assert rec["delegation_basis"] == FACTORY_AUTONOMY_CLAUSE
        assert "factory_autonomy" in FACTORY_AUTONOMY_CLAUSE

    async def test_github_bot_actor_is_delegated_bot(self, config, monkeypatch) -> None:
        """GitHub App actors (is_bot=true) are the bot lane even if not our token."""
        fake = FakeGh(
            merged=[{"number": 6, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={
                6: _detail(6, approver="github-actions[bot]", approver_is_bot=True)
            },
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role"] == ROLE_DELEGATED_BOT
        assert rec["delegation_basis"] == FACTORY_AUTONOMY_CLAUSE

    async def test_role_separated_false_when_author_merges_own_pr(
        self, config, monkeypatch
    ) -> None:
        fake = FakeGh(
            merged=[{"number": 8, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={8: _detail(8, author=HUMAN_LOGIN, approver=HUMAN_LOGIN)},
        )
        _install(monkeypatch, fake)

        await ApprovalRecordReconciler(config).reconcile()

        rec = _read_records(config)[0]
        assert rec["role_separated"] is False


class TestDedupAndIdempotency:
    async def test_already_recorded_pr_is_skipped(self, config, monkeypatch) -> None:
        """Read-back dedup: a PR already in the stream is never re-fetched."""
        chain = AuditChain(config.approval_records_path)
        chain.append({"pr_number": 42, "timestamp": "2026-07-08T00:00:00Z"})
        fake = FakeGh(merged=[{"number": 42, "mergedAt": "2026-07-08T12:00:00Z"}])
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"merged_seen": 1, "recorded": 0, "capture_gap_risk": False}
        assert fake.calls_starting("gh", "pr", "view") == []
        assert fake.calls_starting("gh", "api", "user") == []

    async def test_two_ticks_record_once(self, config, monkeypatch) -> None:
        fake = FakeGh(
            merged=[{"number": 9, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={9: _detail(9)},
        )
        _install(monkeypatch, fake)
        reconciler = ApprovalRecordReconciler(config)

        first = await reconciler.reconcile()
        second = await reconciler.reconcile()

        assert first["recorded"] == 1
        assert second["recorded"] == 0
        assert len(_read_records(config)) == 1

    async def test_duplicate_list_entries_record_once(
        self, config, monkeypatch
    ) -> None:
        """A duplicated number inside ONE list payload must not double-append
        (read-back dedup only covers previous ticks)."""
        fake = FakeGh(
            merged=[
                {"number": 11, "mergedAt": "2026-07-08T12:00:00Z"},
                {"number": 11, "mergedAt": "2026-07-08T12:00:00Z"},
            ],
            details={11: _detail(11)},
        )
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result["recorded"] == 1
        assert [r["pr_number"] for r in _read_records(config)] == [11]

    async def test_break_glass_record_does_not_poison_dedup(
        self, config, monkeypatch
    ) -> None:
        """A CH-3 break-glass record for PR #13 must not suppress the later
        approval record for the same merge — dedup counts approvals only."""
        chain = AuditChain(config.approval_records_path)
        chain.append(
            {
                "record_type": RECORD_TYPE_BREAK_GLASS,
                "pr_number": 13,
                "timestamp": "2026-07-08T00:00:00Z",
            }
        )
        fake = FakeGh(
            merged=[{"number": 13, "mergedAt": "2026-07-08T12:00:00Z"}],
            details={13: _detail(13)},
        )
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result["recorded"] == 1
        approvals = [
            r for r in _read_records(config) if r.get("record_type") == "approval"
        ]
        assert [r["pr_number"] for r in approvals] == [13]

    async def test_steady_state_makes_single_gh_call(self, config, monkeypatch) -> None:
        """No new merges → one list call, no identity/detail calls."""
        fake = FakeGh(merged=[])
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"merged_seen": 0, "recorded": 0, "capture_gap_risk": False}
        assert len(fake.calls) == 1
        assert fake.calls[0][:3] == ("gh", "pr", "list")


class TestCaptureGapDetection:
    """Continuity evidence (review finding): a fixed scan window cannot prove
    completeness after downtime. Zero overlap between the window and the
    recorded stream means merges may have passed the horizon unrecorded —
    the gap itself must become chained evidence, never silence."""

    async def test_no_overlap_with_recorded_stream_chains_gap_marker(
        self, config, monkeypatch
    ) -> None:
        fake = FakeGh(
            merged=[{"number": 10, "mergedAt": "2026-07-08T10:00:00Z"}],
            details={10: _detail(10)},
        )
        _install(monkeypatch, fake)
        reconciler = ApprovalRecordReconciler(config)
        await reconciler.reconcile()

        # The next tick's window holds only newer merges — PR 10 fell past
        # the horizon, so continuity with the recorded stream is unprovable.
        fake.merged = [{"number": 70, "mergedAt": "2026-07-08T18:00:00Z"}]
        fake.details = {70: _detail(70)}
        result = await reconciler.reconcile()

        assert result == {"merged_seen": 1, "recorded": 1, "capture_gap_risk": True}
        markers = [
            r for r in _read_records(config) if r.get("record_type") == "capture_gap"
        ]
        assert len(markers) == 1
        assert markers[0]["scanned"] == 1
        assert markers[0]["new_unrecorded"] == 1
        assert AuditChain(config.approval_records_path).verify().ok

    async def test_overlap_with_recorded_stream_is_continuity(
        self, config, monkeypatch
    ) -> None:
        """One already-recorded PR in the window anchors continuity."""
        fake = FakeGh(
            merged=[{"number": 10, "mergedAt": "2026-07-08T10:00:00Z"}],
            details={10: _detail(10)},
        )
        _install(monkeypatch, fake)
        reconciler = ApprovalRecordReconciler(config)
        await reconciler.reconcile()

        fake.merged = [
            {"number": 10, "mergedAt": "2026-07-08T10:00:00Z"},
            {"number": 11, "mergedAt": "2026-07-08T11:00:00Z"},
        ]
        fake.details = {10: _detail(10), 11: _detail(11)}
        result = await reconciler.reconcile()

        assert result == {"merged_seen": 2, "recorded": 1, "capture_gap_risk": False}
        assert [
            r for r in _read_records(config) if r.get("record_type") == "capture_gap"
        ] == []

    async def test_adoption_tick_on_empty_stream_is_baseline_not_gap(
        self, config, monkeypatch
    ) -> None:
        """The first-ever tick has nothing to be continuous WITH — that is
        the documented adoption baseline, not a capture gap."""
        fake = FakeGh(
            merged=[{"number": 10, "mergedAt": "2026-07-08T10:00:00Z"}],
            details={10: _detail(10)},
        )
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"merged_seen": 1, "recorded": 1, "capture_gap_risk": False}
        assert [
            r for r in _read_records(config) if r.get("record_type") == "capture_gap"
        ] == []


class TestOutagesAndGates:
    async def test_gh_outage_propagates_to_cycle_handler(
        self, config, monkeypatch
    ) -> None:
        """No broad except: a gh failure raises out of reconcile()."""

        async def _boom(*_cmd: str, **_kwargs: Any) -> str:
            raise RuntimeError("Command ('gh',...) failed (rc=1): HTTP 502")

        monkeypatch.setattr(subprocess_util, "run_subprocess", _boom)

        with pytest.raises(RuntimeError, match="502"):
            await ApprovalRecordReconciler(config).reconcile()
        assert _read_records(config) == []

    async def test_partial_failure_preserves_progress_and_self_heals(
        self, config, monkeypatch
    ) -> None:
        """PR 1 records, PR 2's fetch fails → error propagates, PR 1 kept;
        the next tick records PR 2 without duplicating PR 1."""
        merged = [
            {"number": 1, "mergedAt": "2026-07-08T10:00:00Z"},
            {"number": 2, "mergedAt": "2026-07-08T11:00:00Z"},
        ]
        failing = FakeGh(
            merged=merged,
            details={1: _detail(1), 2: RuntimeError("gh: HTTP 503")},
        )
        _install(monkeypatch, failing)
        reconciler = ApprovalRecordReconciler(config)

        with pytest.raises(RuntimeError, match="503"):
            await reconciler.reconcile()
        assert [r["pr_number"] for r in _read_records(config)] == [1]

        recovered = FakeGh(merged=merged, details={1: _detail(1), 2: _detail(2)})
        _install(monkeypatch, recovered)
        result = await reconciler.reconcile()

        assert result == {"merged_seen": 2, "recorded": 1, "capture_gap_risk": False}
        assert [r["pr_number"] for r in _read_records(config)] == [1, 2]
        assert AuditChain(config.approval_records_path).verify().ok

    async def test_dry_run_makes_no_gh_calls(self, tmp_path, monkeypatch) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo", dry_run=True)
        fake = FakeGh()
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"status": "dry_run"}
        assert fake.calls == []

    async def test_kill_switch_disables_reconciliation(
        self, tmp_path, monkeypatch
    ) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo", approval_records_enabled=False
        )
        fake = FakeGh()
        _install(monkeypatch, fake)

        result = await ApprovalRecordReconciler(config).reconcile()

        assert result == {"status": "config_disabled"}
        assert fake.calls == []
