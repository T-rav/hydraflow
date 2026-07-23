"""Regression: 23 orphaned principles_audit epics in one day (#9855, #9805).

Three compounding defects, each pinned here:
1. The decomposer's child label (``auto-decomposed-child``) was never
   registered repo-wide, so every child creation hard-failed and each epic
   was born childless — and the orphan epic was left OPEN as litter.
2. ``principles_audit``'s ``_reconcile_onboarding``/``_retry_blocked`` had no
   per-target isolation: one unreachable managed repo killed the whole tick,
   pegging ``tick_error_ratio=1.0`` (#9805 — recurred 6×).
3. ``TrustFleetSanityLoop`` cleared the anomaly dedup key when the filed
   issue closed — but triage closes it BY DECOMPOSING it, so an unresolved
   anomaly minted a fresh epic every cycle.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from models import EpicDecompResult, NewIssueSpec
from prep import HYDRAFLOW_LABELS, HYDRAFLOW_LITERAL_LABELS
from principles_audit_loop import PrinciplesAuditLoop
from subprocess_util import CreditExhaustedError
from trust_fleet_sanity_loop import TrustFleetSanityLoop


def test_decomposer_labels_are_registered_at_startup() -> None:
    config_fields = {row[0] for row in HYDRAFLOW_LABELS}
    literals = {row[0] for row in HYDRAFLOW_LITERAL_LABELS}

    assert "auto_decomposed_child_label" in config_fields  # root cause 1
    assert "sandbox-fail-auto-fix" in literals  # #9914 durable check
    assert "sandbox-hitl" in literals


class TestPerTargetIsolation:
    @staticmethod
    def _loop(repos, audit_side_effects):
        state = MagicMock()
        state.get_onboarding_status = MagicMock(return_value=None)
        state.set_onboarding_status = MagicMock()
        loop = SimpleNamespace(
            _config=SimpleNamespace(managed_repos=repos),
            _state=state,
            _run_onboarding_audit=AsyncMock(side_effect=audit_side_effects),
        )
        return loop

    @pytest.mark.asyncio
    async def test_one_unreachable_target_does_not_kill_the_tick(self) -> None:
        repos = [
            SimpleNamespace(enabled=True, slug="acme/dead"),
            SimpleNamespace(enabled=True, slug="acme/alive"),
        ]
        loop = self._loop(repos, [RuntimeError("unreachable"), None])

        count = await PrinciplesAuditLoop._reconcile_onboarding(loop)

        assert count == 1  # the healthy target was still processed
        assert loop._run_onboarding_audit.await_count == 2

    @pytest.mark.asyncio
    async def test_credit_exhaustion_still_propagates(self) -> None:
        repos = [SimpleNamespace(enabled=True, slug="acme/x")]
        loop = self._loop(repos, [CreditExhaustedError("cap")])

        with pytest.raises(CreditExhaustedError):
            await PrinciplesAuditLoop._reconcile_onboarding(loop)


class TestAnomalyMintGuard:
    @pytest.mark.asyncio
    async def test_open_escalation_is_reused_instead_of_refiled(self) -> None:
        loop = SimpleNamespace(
            _find_open_escalation=AsyncMock(return_value=77),
            _pr=MagicMock(create_issue=AsyncMock()),
            _config=MagicMock(),
        )

        number = await TrustFleetSanityLoop._file_anomaly(
            loop, "principles_audit", "tick_error_ratio", {"ratio": 1.0}
        )

        assert number == 77
        loop._pr.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_open_escalation_files_normally(self) -> None:
        loop = SimpleNamespace(
            _find_open_escalation=AsyncMock(return_value=0),
            _pr=MagicMock(create_issue=AsyncMock(return_value=101)),
            _config=MagicMock(),
        )

        number = await TrustFleetSanityLoop._file_anomaly(
            loop, "principles_audit", "tick_error_ratio", {"ratio": 1.0}
        )

        assert number == 101
        loop._pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_childless_decomposition_closes_the_orphan_epic(
    tmp_path: Path,
) -> None:
    from issue_decomposer import IssueDecomposer
    from mockworld.fakes.fake_github import FakeGitHub
    from tests.conftest import TaskFactory
    from tests.helpers import ConfigFactory, make_tracker

    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    decomposer = IssueDecomposer(prs, epic_manager, make_tracker(tmp_path), config)
    prs.add_issue(10, "Source issue", "Original body")

    real_create = prs.create_issue
    calls = {"n": 0}

    async def epic_only(title, body, labels=None):  # children fail (#9855 rc 1)
        calls["n"] += 1
        if calls["n"] == 1:
            return await real_create(title, body, labels)
        return 0

    prs.create_issue = epic_only  # type: ignore[method-assign]

    result = await decomposer.create_epic_from_result(
        source_task=TaskFactory.create(id=10),
        result=EpicDecompResult(
            should_decompose=True,
            epic_title="Epic: doomed",
            epic_body="## Sub-issues",
            children=[NewIssueSpec(title="Child 1", body="Do 1")],
            reasoning="r",
        ),
    )

    assert result is None  # source stays open for human-required
    epic = next(i for i in prs._issues.values() if i.title == "Epic: doomed")
    assert epic.state == "closed"  # no more orphan litter
    epic_manager.register_epic.assert_not_awaited()
