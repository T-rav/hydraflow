"""MockWorld scenario for the CH-3 (#9731) merge-policy gate.

Pattern B (direct instantiation), following
``test_merge_state_watcher_scenario.py``: ``PostMergeHandler`` — the
factory's post-review Monitor merge seam — drives ``FakeGitHub`` through
``handle_approved`` under three policy states:

* the packaged default policy — the pipeline-approved merge lands
  (``FakeGitHub`` records the PR merged, no escalation);
* an operator-tightened repo-local policy — the merge is BLOCKED and the
  issue escalates to HITL instead of merging;
* the tightened policy plus a ``policy-override:<reason-slug>`` label on the
  fake PR — the merge lands and a ``break_glass`` record is chained onto
  the CH-2 approval-records stream (fake gh transport at the subprocess
  boundary serves the FakeGitHub PR's own labels).

The label transport is faked at the subprocess boundary (definition site),
same as the CH-2 approval-record scenario.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

import subprocess_util
from approval_records import RECORD_TYPE_BREAK_GLASS
from audit_chain import AuditChain
from events import EventBus, EventType
from mockworld.fakes import FakeGitHub
from models import MergeApprovalContext
from post_merge_handler import PostMergeHandler
from state import StateTracker
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import STRICT_MERGE_POLICY, ConfigFactory, install_repo_merge_policy

pytestmark = pytest.mark.scenario_loops

_PR_NUMBER = 101
_ISSUE_NUMBER = 42


def _fake_label_transport(monkeypatch, github: FakeGitHub) -> list[tuple[str, ...]]:
    """gh label reads answered from the FakeGitHub PR's own labels."""
    calls: list[tuple[str, ...]] = []

    async def _run(*cmd: str, **_kwargs) -> str:
        calls.append(cmd)
        assert cmd[:3] == ("gh", "pr", "view")
        pr = github.pr(int(cmd[3]))
        return json.dumps({"labels": [{"name": name} for name in pr.labels]})

    monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
    return calls


def _make_world(tmp_path):
    """One seeded world: config, handler, FakeGitHub, and a ready ctx."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    github = FakeGitHub()
    github.add_issue(
        number=_ISSUE_NUMBER,
        title="Fix the frobnicator",
        body="The frobnicator is broken.",
    )
    github.add_pr(
        number=_PR_NUMBER,
        issue_number=_ISSUE_NUMBER,
        branch=f"agent/issue-{_ISSUE_NUMBER}",
    )
    handler = PostMergeHandler(
        config=config,
        state=StateTracker(config.state_file),
        prs=github,
        event_bus=EventBus(),
        ac_generator=None,
        retrospective=None,
        verification_judge=None,
        epic_checker=None,
    )
    ctx = MergeApprovalContext(
        pr=PRInfoFactory.create(number=_PR_NUMBER, issue_number=_ISSUE_NUMBER),
        issue=TaskFactory.create(id=_ISSUE_NUMBER),
        result=ReviewResultFactory.create(
            pr_number=_PR_NUMBER, issue_number=_ISSUE_NUMBER
        ),
        diff="diff --git a/x b/x",
        worker_id=0,
        ci_gate_fn=AsyncMock(return_value=True),
        escalate_fn=AsyncMock(),
        publish_fn=AsyncMock(),
    )
    return config, handler, github, ctx


class TestMergePolicyScenario:
    """CH-3 — the policy gate on the post-review merge seam, end to end."""

    async def test_default_policy_reviewed_merge_lands(
        self, tmp_path, monkeypatch
    ) -> None:
        """Packaged table policy: the pipeline-approved merge goes through."""
        config, handler, github, ctx = _make_world(tmp_path)
        transport_calls = _fake_label_transport(monkeypatch, github)

        await handler.handle_approved(ctx)

        assert github.pr(_PR_NUMBER).merged is True
        ctx.escalate_fn.assert_not_awaited()
        assert transport_calls == [], (
            "v1 default policy has no matchers — the allow path must not read PR labels"
        )
        assert not config.approval_records_path.exists()

    async def test_tightened_policy_blocks_merge_and_escalates(
        self, tmp_path, monkeypatch
    ) -> None:
        """Operator-tightened policy: deny blocks the merge + HITL escalation."""
        config, handler, github, ctx = _make_world(tmp_path)
        install_repo_merge_policy(config, STRICT_MERGE_POLICY)
        _fake_label_transport(monkeypatch, github)

        await handler.handle_approved(ctx)

        assert github.pr(_PR_NUMBER).merged is False
        ctx.escalate_fn.assert_awaited_once()
        escalation = ctx.escalate_fn.await_args.args[0]
        assert escalation.cause.startswith("Blocked by merge policy")
        assert escalation.issue_number == _ISSUE_NUMBER
        alerts = [
            e for e in handler._bus.get_history() if e.type == EventType.SYSTEM_ALERT
        ]
        assert [a.data["source"] for a in alerts] == ["merge_policy"]

    async def test_break_glass_label_merges_and_chains_record(
        self, tmp_path, monkeypatch
    ) -> None:
        """policy-override:<slug> on the PR: merge lands, break_glass chained."""
        config, handler, github, ctx = _make_world(tmp_path)
        install_repo_merge_policy(config, STRICT_MERGE_POLICY)
        github.add_pr_label(_PR_NUMBER, "policy-override:hotfix-prod-outage")
        _fake_label_transport(monkeypatch, github)

        await handler.handle_approved(ctx)

        assert github.pr(_PR_NUMBER).merged is True
        ctx.escalate_fn.assert_not_awaited()
        records = [
            json.loads(line)
            for line in config.approval_records_path.read_text().splitlines()
        ]
        assert len(records) == 1
        record = records[0]
        assert record["record_type"] == RECORD_TYPE_BREAK_GLASS
        assert record["pr_number"] == _PR_NUMBER
        assert record["lane"] == "post_merge_handler"
        assert record["override_label"] == "policy-override:hotfix-prod-outage"
        assert record["reason_slug"] == "hotfix-prod-outage"
        assert AuditChain(config.approval_records_path).verify().ok

    async def test_kill_switch_restores_ungated_behavior(
        self, tmp_path, monkeypatch
    ) -> None:
        """merge_policy_enabled=False merges even under the strict policy."""
        config, handler, github, ctx = _make_world(tmp_path)
        install_repo_merge_policy(config, STRICT_MERGE_POLICY)
        object.__setattr__(config, "merge_policy_enabled", False)
        transport_calls = _fake_label_transport(monkeypatch, github)

        await handler.handle_approved(ctx)

        assert github.pr(_PR_NUMBER).merged is True
        ctx.escalate_fn.assert_not_awaited()
        assert transport_calls == []
