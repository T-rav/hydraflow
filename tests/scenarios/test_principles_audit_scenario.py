"""MockWorld scenario for PrinciplesAuditLoop (spec §4.4).

Two scenarios cover the loop's ends-of-the-world:

* ``test_onboarding_blocked_files_issue`` — a newly-added managed repo
  whose audit reports a P1 FAIL must flip its onboarding status to
  ``"blocked"`` and file a ``hydraflow-find`` + ``onboarding-blocked``
  issue via the stubbed ``PRPort``.
* ``test_drift_regression_files_find_issue`` — HydraFlow-self was
  all-green on the prior tick (``state.get_last_green_audit`` returns
  a snapshot with ``P1.1: PASS``) but the current audit reports
  ``P1.1: FAIL``. The loop must file one ``hydraflow-find`` +
  ``principles-drift`` + ``check-P1.1`` issue.

The loop's external surface — ``_run_audit`` (``make audit-json``
subprocess) and ``_refresh_checkout`` (``git clone``/``git fetch``) —
is stubbed via the ``principles_audit_run_audit`` /
``principles_audit_refresh_checkout`` port keys seeded through
:func:`tests.scenarios.helpers.loop_port_seeding.seed_ports`. The
builder also pins ``config.data_root`` under the tmp sandbox so
``_save_snapshot`` writes stay contained.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _finding(
    *,
    check_id: str,
    status: str,
    principle: str = "P1",
    severity: str = "STRUCTURAL",
) -> dict[str, Any]:
    """Build a minimum-viable finding row the loop's formatters accept."""
    return {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "principle": principle,
        "source": f"docs/adr/{principle.lower()}",
        "what": f"{check_id} gate",
        "remediation": f"repair {check_id}",
        "message": "" if status == "PASS" else "check failed",
    }


def _stateful_onboarding_mock(initial: dict[str, str] | None = None) -> MagicMock:
    """MagicMock that round-trips ``set_onboarding_status`` writes.

    The loop calls ``set_onboarding_status`` then ``get_onboarding_status``
    within the same tick (pending → blocked → retry-blocked iteration),
    so a static ``return_value`` would mis-simulate the flow. Backing the
    mock with a real dict preserves ordering without reaching for
    StateTracker's real JSON persistence.
    """
    store: dict[str, str] = dict(initial or {})
    state = MagicMock()
    state.get_onboarding_status.side_effect = store.get
    state.set_onboarding_status.side_effect = store.__setitem__
    state.blocked_slugs.side_effect = lambda: {
        slug for slug, status in store.items() if status == "blocked"
    }
    state.get_last_green_audit.return_value = {}
    state.set_last_green_audit.return_value = None
    state.get_drift_attempts.return_value = 0
    state.increment_drift_attempts.return_value = 1
    state._store = store  # expose for test assertions
    return state


class TestPrinciplesAuditScenario:
    """§4.4 — onboarding gate + drift detector MockWorld scenarios."""

    async def test_onboarding_blocked_files_issue(self, tmp_path) -> None:
        """New managed repo with a P1 FAIL → onboarding flips to blocked + issue filed."""
        from config import ManagedRepo  # noqa: PLC0415

        world = MockWorld(tmp_path)

        # Current audit: one P1 FAIL + one passing hydraflow-self check.
        failing_report = {
            "findings": [
                _finding(check_id="P1.1", status="FAIL", principle="P1"),
                _finding(check_id="P2.4", status="PASS", principle="P2"),
            ]
        }
        # hydraflow-self: also returns the same report. Since the
        # state mock's last-green is empty, ``_diff_regressions`` is a
        # no-op for the self-audit and nothing is filed for it.
        run_audit = AsyncMock(return_value=failing_report)

        # ``_refresh_checkout`` is called once per managed slug. Return a
        # path under tmp_path so the builder-level data_root pin keeps
        # snapshot writes inside the sandbox.
        refresh_checkout = AsyncMock(return_value=tmp_path / "acme-widget-checkout")

        state = _stateful_onboarding_mock()

        _seed_ports(
            world,
            principles_audit_state=state,
            principles_audit_run_audit=run_audit,
            principles_audit_refresh_checkout=refresh_checkout,
            principles_audit_managed_repos=[ManagedRepo(slug="acme/widget")],
        )

        stats = await world.run_with_loops(["principles_audit"], cycles=1)

        # Onboarding path ran exactly once for the new slug.
        assert stats["principles_audit"]["onboarded"] == 1, stats
        # Slug is now marked blocked in the stateful mock.
        assert state._store.get("acme/widget") == "blocked"

        # The loop filed at least the onboarding issue. Find it by label.
        issues = await world.github.list_issues_by_label("onboarding-blocked")
        assert len(issues) == 1
        labels = world.github.issue(issues[0]["number"]).labels
        assert "hydraflow-find" in labels
        assert "onboarding-blocked" in labels

    async def test_drift_regression_files_find_issue(self, tmp_path) -> None:
        """Hydraflow-self was green; current audit fails one check → drift issue filed."""
        world = MockWorld(tmp_path)

        # State: hydraflow-self was all-green last tick.
        state = MagicMock()
        state.get_onboarding_status.return_value = None
        state.get_last_green_audit.side_effect = lambda slug: (
            {"P1.1": "PASS", "P2.4": "PASS"} if slug == "hydraflow-self" else {}
        )
        state.set_last_green_audit.return_value = None
        state.set_onboarding_status.return_value = None
        state.get_drift_attempts.return_value = 0
        state.increment_drift_attempts.return_value = 1  # < _STRUCTURAL_ATTEMPTS=3
        state.blocked_slugs.return_value = set()

        # Current audit: P1.1 PASS → FAIL regression, P2.4 still PASS.
        drifted_report = {
            "findings": [
                _finding(check_id="P1.1", status="FAIL", principle="P1"),
                _finding(check_id="P2.4", status="PASS", principle="P2"),
            ]
        }
        run_audit = AsyncMock(return_value=drifted_report)

        _seed_ports(
            world,
            principles_audit_state=state,
            principles_audit_run_audit=run_audit,
            # No managed_repos → only hydraflow-self audits.
            principles_audit_managed_repos=[],
        )

        stats = await world.run_with_loops(["principles_audit"], cycles=1)

        # One managed-nothing, one hydraflow-self audit.
        assert stats["principles_audit"]["audited"] == 1, stats
        assert stats["principles_audit"]["regressions_filed"] == 1, stats
        # Structural severity + attempts=1 → no escalation on first fire.
        assert stats["principles_audit"]["escalations_filed"] == 0, stats

        # Exactly one issue filed with the drift label set.
        issues = await world.github.list_issues_by_label("principles-drift")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        assert "P1.1" in issue.title
        assert "hydraflow-self" in issue.title
        assert "hydraflow-find" in issue.labels
        assert "principles-drift" in issue.labels
        assert "check-P1.1" in issue.labels

    async def test_reconcile_closed_escalations_via_pr_port(self, tmp_path) -> None:
        """Closing a principles-stuck issue clears the attempt counter via PRPort.

        Verifies the advisor-0dmd fix: _reconcile_closed_escalations now routes
        through PRPort.list_closed_issues_by_label instead of spawning a raw
        ``gh`` subprocess. MockWorld can stub the port; no real process needed.
        """
        world = MockWorld(tmp_path)

        # One closed principles-stuck issue whose title encodes (slug, check_id).
        world.github.add_issue(
            77,
            "Principles drift stuck: P3.2 in acme/widget",
            "",
            labels=["principles-stuck"],
        )
        await world.github.close_issue(77)

        state = _stateful_onboarding_mock()
        # Simulate that the escalation counter was previously incremented.
        state.reset_drift_attempts = MagicMock()

        # All-green audit so no regressions are filed — keeps scenario focused
        # on the reconcile path alone.
        all_green_report = {
            "findings": [_finding(check_id="P3.2", status="PASS", principle="P3")]
        }
        run_audit = AsyncMock(return_value=all_green_report)

        _seed_ports(
            world,
            principles_audit_state=state,
            principles_audit_run_audit=run_audit,
            principles_audit_managed_repos=[],
        )

        await world.run_with_loops(["principles_audit"], cycles=1)

        # Counter reset for the parsed (slug, check_id) pair.
        state.reset_drift_attempts.assert_called_once_with("acme/widget", "P3.2")
