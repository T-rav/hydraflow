"""MockWorld scenario for AdrTouchpointAuditorLoop (ADR-0056).

Drives the loop end-to-end with a stubbed `gh pr list` and a real
``ADRIndex`` over an on-disk fixture, asserts that drift in a single
merged PR produces exactly one `hydraflow-find` issue with the right
labels.

External surface stubbed via the scenario port-seeding pattern (mirrors
the F7 FlakeTracker / S6 SkillPromptEval / fake-coverage scenarios):

* ``adr_touchpoint_list_merged_prs`` → replaces ``gh pr list``.
* ``adr_touchpoint_reconcile_closed`` → no-op for closed-issue reconcile.
* ``adr_touchpoint_index`` → real ``ADRIndex`` over the seeded ADR dir.

HITL-escalation scenario (bead advisor-mj4p):
* An existing per-ADR rollup open after two prior ticks (attempts=2) sees a
  third drifting PR. On this tick ``inc_adr_audit_attempts`` returns 3 (==
  ``_MAX_ATTEMPTS``), triggering ``_file_drift_escalation``.
* The escalation issue carries ``hydraflow-hitl-escalation`` +
  ``hydraflow-adr-drift-stuck``.
* ``hydraflow-adr-drift-stuck`` is NOT in ``auto_agent_skip_sublabels``, so
  the AutoAgentPreflightLoop will pick up the issue (ADR-0050 preflight
  reachable).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _write_adr(adr_dir, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


class TestAdrTouchpointAuditor:
    """ADR-0056 — drift detection MockWorld scenarios (per-ADR rollup #8987)."""

    async def test_drift_files_one_rollup(self, tmp_path) -> None:
        """Merged PR touches an ADR-cited src/ file → one rollup issue filed."""
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=2001)
        fake_pr.update_issue_body = AsyncMock(return_value=None)
        fake_pr.close_issue = AsyncMock(return_value=None)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8473,
                    "mergedAt": "2026-05-06T20:00:00Z",
                    "title": "feat: tweak agent",
                    "files": [{"path": "src/agent.py"}, {"path": "tests/x.py"}],
                }
            ]

        # Seed cursor so the loop scans (empty cursor would seed-and-return).
        from unittest.mock import MagicMock  # noqa: PLC0415

        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_audit_attempts.return_value = 0
        state.inc_adr_audit_attempts.return_value = 1
        state.get_adr_rollup.return_value = None

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title, body, labels = fake_pr.create_issue.await_args.args
        assert "ADR-0024" in title
        assert "1 PR" in title
        assert "#8473" in body
        assert "hydraflow-find" in labels
        assert "hydraflow-adr-drift" in labels

    async def test_three_prs_drifting_same_adr_one_rollup(self, tmp_path) -> None:
        """3 PRs drifting the same ADR file ONE rollup with all PRs in body."""
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=2010)
        fake_pr.update_issue_body = AsyncMock(return_value=None)
        fake_pr.close_issue = AsyncMock(return_value=None)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8501,
                    "mergedAt": "2026-05-07T10:00:00Z",
                    "files": [{"path": "src/agent.py"}],
                },
                {
                    "number": 8502,
                    "mergedAt": "2026-05-07T11:00:00Z",
                    "files": [{"path": "src/agent.py"}],
                },
                {
                    "number": 8503,
                    "mergedAt": "2026-05-07T12:00:00Z",
                    "files": [{"path": "src/agent.py"}],
                },
            ]

        from unittest.mock import MagicMock  # noqa: PLC0415

        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_audit_attempts.return_value = 0
        state.inc_adr_audit_attempts.return_value = 1
        state.get_adr_rollup.return_value = None

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        body = fake_pr.create_issue.await_args.args[1]
        for n in (8501, 8502, 8503):
            assert f"#{n}" in body

    async def test_no_drift_when_adr_in_diff(self, tmp_path) -> None:
        """ADR file in the diff → no issue filed."""
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=2002)
        fake_pr.update_issue_body = AsyncMock(return_value=None)
        fake_pr.close_issue = AsyncMock(return_value=None)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8474,
                    "mergedAt": "2026-05-06T21:00:00Z",
                    "files": [
                        {"path": "src/agent.py"},
                        {"path": "docs/adr/0024-alpha.md"},
                    ],
                }
            ]

        from unittest.mock import MagicMock  # noqa: PLC0415

        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_audit_attempts.return_value = 0
        state.inc_adr_audit_attempts.return_value = 1
        state.get_adr_rollup.return_value = None

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        fake_pr.create_issue.assert_not_awaited()

    async def test_third_strike_files_hitl_escalation(self, tmp_path) -> None:
        """Third consecutive drift tick against an open rollup triggers HITL escalation.

        Setup:
        - ADR-0024 has an open rollup from two prior ticks (attempts already at
          2 before this tick).
        - A third PR drifts ADR-0024 this tick; ``inc_adr_audit_attempts`` returns
          3 (== ``_MAX_ATTEMPTS``).
        - The loop must call ``_file_drift_escalation`` with the rollup key and
          file an issue carrying ``hydraflow-hitl-escalation`` +
          ``hydraflow-adr-drift-stuck``.
        - ``hydraflow-adr-drift-stuck`` must NOT be in
          ``config.auto_agent_skip_sublabels`` — confirming the AutoAgentPreflightLoop
          preflight path (ADR-0050) is reachable for this escalation class.
        """
        from unittest.mock import MagicMock  # noqa: PLC0415

        from adr_index import ADRIndex  # noqa: PLC0415
        from config import HydraFlowConfig  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        # The escalation issue gets number 3001.
        fake_pr.create_issue = AsyncMock(return_value=3001)
        fake_pr.update_issue_body = AsyncMock(return_value=None)
        fake_pr.close_issue = AsyncMock(return_value=None)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        # Open rollup from two prior ticks.
        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_rollup.return_value = {
            "issue_number": 2999,
            "pr_numbers": [8510, 8511],
        }
        # Third tick → attempt counter hits _MAX_ATTEMPTS.
        state.inc_adr_audit_attempts.return_value = 3

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8512,
                    "mergedAt": "2026-05-08T10:00:00Z",
                    "title": "feat: more agent tweaks",
                    "files": [{"path": "src/agent.py"}],
                }
            ]

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        # Exactly one issue filed — the HITL escalation (no new rollup).
        assert fake_pr.create_issue.await_count == 1
        title, body, labels = fake_pr.create_issue.await_args.args

        # Title identifies the rollup key and attempt count.
        assert "HITL" in title
        assert "ADR-0024" in title
        assert "3" in title

        # Body mentions the dedup key so a human can correlate with the rollup.
        assert "ADR-0024" in body

        # Required labels: hitl-escalation + adr-drift-stuck.
        assert "hydraflow-hitl-escalation" in labels
        assert "hydraflow-adr-drift-stuck" in labels

        # ADR-0050 preflight reachability: hydraflow-adr-drift-stuck must NOT
        # be in the auto-agent deny list, so AutoAgentPreflightLoop can pick
        # this issue up for autonomous triage.
        cfg = HydraFlowConfig()
        deny_list = cfg.auto_agent_skip_sublabels
        assert "hydraflow-adr-drift-stuck" not in deny_list, (
            "hydraflow-adr-drift-stuck must not be in auto_agent_skip_sublabels — "
            "AutoAgentPreflightLoop (ADR-0050) must be reachable for this escalation class"
        )
