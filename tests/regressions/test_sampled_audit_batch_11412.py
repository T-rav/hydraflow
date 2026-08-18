"""Pins for the 2026-08-18 sampled-audit findings on the night's merges.

The re-audit loop caught four real defects in changes that had each
passed review and full quality. Every one is pinned here so the audit's
work becomes a permanent guard rather than a one-time correction.

- #11412 (on #11370): only ONE of two parse-failure paths carried the
  infra classification. The schema-violation path — exactly the weak
  structured-output compliance the failover lane exhibits — still
  escalated to HITL, reproducing the incident the fix claimed to close.
- #11413 (on #11372): the fail-loud PR's safety claim ("no loop relied on
  the silent empty answer") was falsified — StaleIssueLoop's branch-GC
  makes two real `gh api` calls the fake never modelled, which fail-loud
  would now RAISE on.
- #11408 (on #11390): `advisory_labels or DEFAULT` silently substituted
  the module default for an explicitly-empty set — retiring issues the
  caller excluded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import credit_failover
from backlog_budget import retirement_picks
from mockworld.fakes.fake_github import FakeGitHub
from models import EscalationContext


@pytest.mark.asyncio
async def test_schema_violation_fallback_is_infra_under_failover(tmp_path) -> None:
    """#11412: a JSON block that parses but fails validation is the SECOND
    reachable weak-compliance path and must classify as infra too."""
    from diagnostic_runner import DiagnosticRunner

    runner = DiagnosticRunner.__new__(DiagnosticRunner)
    runner._config = MagicMock(repo_root=tmp_path)
    runner._mockworld_diagnosis = lambda: None
    runner._build_command = lambda: ["fake-agent"]
    # Parses as JSON, violates DiagnosisResult's schema (no root_cause etc).
    runner._execute = AsyncMock(return_value='```json\n{"unexpected": true}\n```')
    ctx = EscalationContext(cause="build failure", origin_phase="implement")

    credit_failover.engage(now=datetime.now(UTC), resume_at=None, cooldown_minutes=15)
    try:
        result = await runner.diagnose(1, "t", "b", ctx)
    finally:
        credit_failover.reset_for_tests()

    assert result.infra_failure is True, (
        "a schema-violating diagnosis under failover must park, not escalate "
        "— otherwise #11370's live incident reproduces (#11412)"
    )


@pytest.mark.asyncio
async def test_branch_gc_api_shapes_are_modelled_not_quiet() -> None:
    """#11413: StaleIssueLoop's real gh api reads must be MODELLED — the
    fail-loud default would otherwise raise inside the sandbox."""
    fake = FakeGitHub()
    refs = await fake._run_gh(
        "gh", "api", "repos/o/r/git/matching-refs/heads/agent/", "--jq", "[.[].ref]"
    )
    assert isinstance(json.loads(refs), list)
    commits = await fake._run_gh("gh", "api", "repos/o/r/commits", "--method", "GET")
    assert isinstance(json.loads(commits), list)


def test_explicit_empty_advisory_set_retires_nothing() -> None:
    """#11408: an empty set means 'retire nothing', not 'use the default'."""
    old = (datetime.now(UTC).replace(year=2020)).isoformat()
    issues = [
        {
            "number": n,
            "title": f"i{n}",
            "createdAt": old,
            "labels": [{"name": "hydraflow-find"}],
        }
        for n in range(1, 40)
    ]
    assert (
        retirement_picks(
            issues,
            budget=1,
            min_age_days=0,
            now=datetime.now(UTC),
            advisory_labels=frozenset(),
        )
        == []
    )
