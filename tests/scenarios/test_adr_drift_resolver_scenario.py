"""MockWorld scenario for AdrDriftResolverLoop (#9976).

Drives the loop end-to-end against a rollup issue seeded exactly as
``AdrTouchpointAuditorLoop`` (ADR-0056) would have filed it — a real
``ADRIndex``/ADR-file fixture on disk, a real ``FakeGitHub`` issue with the
same labels the auditor uses — with the TRIAGE LLM boundary FAKED (no real
model calls, per #9976's requirement). Scenarios:

* A CONSISTENT verdict auto-closes the rollup with an audit comment and
  never touches HITL labels.
* A REAL_DRIFT verdict relabels the rollup ``hydraflow-find`` with a
  concrete ADR-edit brief in the body, and leaves it open (the normal
  discover→plan→implement→review pipeline picks it up from there).
* A fleet batch closes when every member ADR triages CONSISTENT.
* #11181 error-flood: a tick's worth of per-ADR triage-call errors still
  spends the tick's real LLM-call budget, so a competing fleet batch is
  correctly deferred instead of overshooting
  ``adr_drift_resolver_max_triage_per_tick``.

Mirrors the port-seeding pattern of
``tests/scenarios/test_adr_touchpoint_auditor_scenario.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _write_adr(adr_dir: Path, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture background for {title}.\n\n"
        f"## Decision\n\nFixture decision text for {title}.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


class TestAdrDriftResolver:
    """#9976 — triage-before-escalate MockWorld scenarios."""

    async def test_consistent_verdict_auto_closes_no_hitl(self, tmp_path) -> None:
        from adr_drift_triage import DriftClassification, TriageVerdict  # noqa: PLC0415
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        # Seed the rollup issue exactly as the auditor would have filed it.
        issue_number = await world.github.create_issue(
            "ADR drift: ADR-0024 cited modules drifted across 1 PR",
            "## ADR drift rollup\n\nPR #8473 changed `src/agent.py`.\n",
            labels=["hydraflow-find", "hydraflow-adr-drift"],
        )
        world.github.seed_pr_diff(
            8473,
            "diff --git a/src/agent.py b/src/agent.py\n"
            "@@ -10,1 +10,1 @@\n"
            "-# old comment\n"
            "+# updated comment wording only\n",
        )

        state = MagicMock()
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": issue_number, "pr_numbers": [8473]},
        }

        triage = MagicMock()
        triage.classify = AsyncMock(
            return_value=TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="Only a comment wording change; the ADR's Decision is untouched.",
            )
        )

        _seed_ports(
            world,
            adr_drift_resolver_state=state,
            adr_drift_resolver_index=adr_index,
            adr_drift_resolver_triage=triage,
        )

        results = await world.run_with_loops(["adr_drift_resolver"], cycles=1)
        assert results["adr_drift_resolver"]["closed"] == 1

        issue = world.github.issue(issue_number)
        assert issue.state == "closed"
        assert "hitl-escalation" not in issue.labels
        assert "hydraflow-adr-drift-stuck" not in issue.labels
        assert any("CONSISTENT" in c.body for c in issue.comments)
        assert any("comment wording change" in c.body for c in issue.comments)

    async def test_real_drift_relabels_to_find_with_brief(self, tmp_path) -> None:
        from adr_drift_triage import DriftClassification, TriageVerdict  # noqa: PLC0415
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=27, title="beta", related=["src/runner.py"])
        adr_index = ADRIndex(adr_dir)

        issue_number = await world.github.create_issue(
            "ADR drift: ADR-0027 cited modules drifted across 1 PR",
            "## ADR drift rollup\n\nPR #9101 changed `src/runner.py`.\n",
            labels=["hydraflow-find", "hydraflow-adr-drift"],
        )
        world.github.seed_pr_diff(
            9101,
            "diff --git a/src/runner.py b/src/runner.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-def run_sync():\n"
            "+async def run_sync():\n",
        )

        state = MagicMock()
        state.all_adr_rollups.return_value = {
            "ADR-0027": {"issue_number": issue_number, "pr_numbers": [9101]},
        }

        triage = MagicMock()
        triage.classify = AsyncMock(
            return_value=TriageVerdict(
                classification=DriftClassification.REAL_DRIFT,
                rationale="The Decision says runs are synchronous; this PR made them async.",
                section="Decision",
            )
        )

        _seed_ports(
            world,
            adr_drift_resolver_state=state,
            adr_drift_resolver_index=adr_index,
            adr_drift_resolver_triage=triage,
        )

        results = await world.run_with_loops(["adr_drift_resolver"], cycles=1)
        assert results["adr_drift_resolver"]["relabeled"] == 1

        issue = world.github.issue(issue_number)
        assert issue.state == "open"
        assert "hydraflow-find" in issue.labels
        assert "hydraflow-adr-drift" not in issue.labels
        assert "hitl-escalation" not in issue.labels
        assert "Decision" in issue.body
        assert "made them async" in issue.body
        assert any("real_drift" in c.body for c in issue.comments)

    async def test_fleet_batch_all_consistent_auto_closes(self, tmp_path) -> None:
        """#10457 — a batched fleet rollup (previously one-shot/human-closed
        only) auto-closes when every member ADR triages CONSISTENT, exactly
        like the auditor would have filed it (adr_numbers persisted)."""
        from adr_drift_triage import DriftClassification, TriageVerdict  # noqa: PLC0415
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=59, title="gamma", related=["src/review_advisor.py"])
        _write_adr(
            adr_dir, number=94, title="delta", related=["src/review_phase/_phase.py"]
        )
        adr_index = ADRIndex(adr_dir)

        issue_number = await world.github.create_issue(
            "ADR drift: fleet PR #9603 drifted 2 ADRs (batched)",
            "## ADR drift rollup — cross-cutting fleet PR (batched)\n\n"
            "PR #9603 changed `src/review_advisor.py`, `src/review_phase/_phase.py`.\n",
            labels=["hydraflow-find", "hydraflow-adr-drift"],
        )
        world.github.seed_pr_diff(
            9603,
            "diff --git a/src/review_advisor.py b/src/review_advisor.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-# old\n"
            "+# refactor only\n",
        )

        state = MagicMock()
        state.all_adr_rollups.return_value = {
            "FLEET-9603": {
                "issue_number": issue_number,
                "pr_numbers": [9603],
                "adr_numbers": [59, 94],
            },
        }

        triage = MagicMock()
        triage.classify = AsyncMock(
            return_value=TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="Implementation-only refactor; the Decision is untouched.",
            )
        )

        _seed_ports(
            world,
            adr_drift_resolver_state=state,
            adr_drift_resolver_index=adr_index,
            adr_drift_resolver_triage=triage,
        )

        results = await world.run_with_loops(["adr_drift_resolver"], cycles=1)
        assert results["adr_drift_resolver"]["fleet_closed"] == 1

        issue = world.github.issue(issue_number)
        assert issue.state == "closed"
        assert "hitl-escalation" not in issue.labels
        assert any("CONSISTENT for all batched ADRs" in c.body for c in issue.comments)

    async def test_error_flood_defers_competing_fleet_batch_within_budget(
        self, tmp_path
    ) -> None:
        """#11181 — a fresh adversarial re-audit of #10474 found that a
        tick's worth of per-ADR triage-CALL errors doesn't reduce the
        fleet gate's computed remaining budget, letting a fleet batch spend
        real LLM calls when the tick's true call volume is already at (or
        over) ``adr_drift_resolver_max_triage_per_tick`` (default 5). Five
        per-ADR rollups all hit a triage-call error (5 real calls spent,
        exhausting the default budget) in the SAME tick as one competing
        fleet batch — the fleet batch must be deferred whole to next tick,
        never touching its issue."""
        from adr_drift_triage import DriftClassification, TriageVerdict  # noqa: PLC0415
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        per_adr_numbers = [11, 12, 13, 14, 15]
        for n in per_adr_numbers:
            _write_adr(
                adr_dir, number=n, title=f"errflood{n}", related=[f"src/m{n}.py"]
            )
        _write_adr(adr_dir, number=16, title="fleetmember", related=["src/m16.py"])
        adr_index = ADRIndex(adr_dir)

        rollups: dict[str, dict] = {}
        for n in per_adr_numbers:
            pr_number = 9000 + n
            issue_number = await world.github.create_issue(
                f"ADR drift: ADR-{n:04d} cited modules drifted",
                f"## ADR drift rollup\n\nPR #{pr_number} changed `src/m{n}.py`.\n",
                labels=["hydraflow-find", "hydraflow-adr-drift"],
            )
            world.github.seed_pr_diff(
                pr_number,
                f"diff --git a/src/m{n}.py b/src/m{n}.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-# old\n"
                "+# churn\n",
            )
            rollups[f"ADR-{n:04d}"] = {
                "issue_number": issue_number,
                "pr_numbers": [pr_number],
            }

        fleet_issue_number = await world.github.create_issue(
            "ADR drift: fleet PR #9700 drifted 1 ADR (batched)",
            "## ADR drift rollup — cross-cutting fleet PR (batched)\n\n"
            "PR #9700 changed `src/m16.py`.\n",
            labels=["hydraflow-find", "hydraflow-adr-drift"],
        )
        world.github.seed_pr_diff(
            9700,
            "diff --git a/src/m16.py b/src/m16.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-# old\n"
            "+# refactor only\n",
        )
        rollups["FLEET-9700"] = {
            "issue_number": fleet_issue_number,
            "pr_numbers": [9700],
            "adr_numbers": [16],
        }

        state = MagicMock()
        state.all_adr_rollups.return_value = rollups

        triage = MagicMock()
        triage.classify = AsyncMock(
            side_effect=[
                RuntimeError("llm call failed"),
                RuntimeError("llm call failed"),
                RuntimeError("llm call failed"),
                RuntimeError("llm call failed"),
                RuntimeError("llm call failed"),
                # Only reached if the (buggy) gate wrongly lets the fleet
                # batch start — kept so a regression fails on the clean
                # assertions below instead of an unhandled StopIteration.
                TriageVerdict(
                    classification=DriftClassification.CONSISTENT,
                    rationale="fleet member ok",
                ),
            ]
        )

        _seed_ports(
            world,
            adr_drift_resolver_state=state,
            adr_drift_resolver_index=adr_index,
            adr_drift_resolver_triage=triage,
        )

        results = await world.run_with_loops(["adr_drift_resolver"], cycles=1)
        stats = results["adr_drift_resolver"]
        assert stats["errors"] == 5
        assert stats["fleet_candidates"] == 1
        assert stats["fleet_triaged"] == 0
        assert stats["fleet_closed"] == 0
        assert triage.classify.await_count == 5

        fleet_issue = world.github.issue(fleet_issue_number)
        assert fleet_issue.state == "open"
        assert fleet_issue.comments == []
