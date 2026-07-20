"""MockWorld scenario for FakeCoverageAuditorLoop (spec §4.7).

Two scenarios covering the two gap subtypes the loop detects:

* ``test_uncassetted_surface_files_adapter_gap`` — a fake's public
  adapter method has no matching cassette. The loop files exactly one
  ``fake-coverage-gap`` + ``adapter-surface`` issue.
* ``test_unused_test_helper_files_helper_gap`` — a fake exposes a
  ``script_*`` helper that no scenario invokes (grep returns False).
  The loop files exactly one ``fake-coverage-gap`` + ``test-helper``
  issue.

The loop's external surface — ``_reconcile_closed_escalations``
(``gh issue list``) and ``_grep_scenario_for_helper`` (``rg`` over
``tests/scenarios/``) — is stubbed via scenario-seeded ports
``fake_coverage_reconcile_closed`` / ``fake_coverage_grep`` which the
catalog builder in ``loop_registrations.py`` reads and monkey-patches
onto the instantiated loop — mirroring the F7 FlakeTracker
(``eac5fc72``) and S6 SkillPromptEval (``93ebf387``) patterns.

On-disk layout is seeded under ``config.repo_root`` (which
``make_bg_loop_deps`` sets to ``<tmp_path>/repo``), so the loop's
``repo / "src" / "mockworld" / "fakes"`` (post-Task-1.1 relocation;
see ADR-0052 landing in PR B) and
``repo / "tests" / "trust" / "contracts" / "cassettes"`` paths resolve
to real seeded files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import yaml

from dedup_store import DedupStore
from state import StateTracker
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestFakeCoverageAuditor:
    """§4.7 — fake-coverage drift MockWorld scenarios."""

    async def test_uncassetted_surface_files_adapter_gap(self, tmp_path) -> None:
        """Public fake method w/o cassette → one adapter-surface gap filed."""
        world = MockWorld(tmp_path)

        # Seed under config.repo_root (= tmp_path / "repo" per make_bg_loop_deps).
        repo = tmp_path / "repo"
        # Seed at the new canonical Fake location (post-Task-1.1 of the
        # sandbox-tier scenario testing track; see ADR-0052 landing in PR B).
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_github.py").write_text(
            "class FakeGitHub:\n"
            "    async def create_issue(self, title, body, labels): ...\n"
            "    async def close_issue(self, num): ...\n"
        )
        cassettes = repo / "tests" / "trust" / "contracts" / "cassettes" / "github"
        cassettes.mkdir(parents=True)
        # Only create_issue is cassetted → close_issue surfaces as the gap.
        (cassettes / "create_issue.yaml").write_text(
            yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
        )

        _seed_ports(
            world,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            # Helpers (none present in this fake) — trivially True to short-circuit.
            fake_coverage_grep=AsyncMock(return_value=True),
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-adapter-surface")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        # #8986 — rollup shape: title names the (fake, kind) pair; the
        # uncovered method names live in the body.
        assert "FakeGitHub" in issue.title
        assert "adapter surface" in issue.title
        assert "close_issue" in issue.body
        assert "hydraflow-adapter-surface" in issue.labels
        assert "hydraflow-fake-coverage-gap" in issue.labels
        assert "hydraflow-find" in issue.labels

    async def test_unused_test_helper_files_helper_gap(self, tmp_path) -> None:
        """Fake ``script_*`` helper with no scenario caller → one test-helper gap."""
        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        # Seed at the new canonical Fake location (post-Task-1.1 of the
        # sandbox-tier scenario testing track; see ADR-0052 landing in PR B).
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_docker.py").write_text(
            "class FakeDocker:\n    def script_run(self, events): ...\n"
        )
        # Empty docker cassette dir so no spurious surface filings fire
        # (script_run is a helper, not adapter surface, so it wouldn't anyway).
        (repo / "tests" / "trust" / "contracts" / "cassettes" / "docker").mkdir(
            parents=True
        )

        _seed_ports(
            world,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=False),  # helper uncalled
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        issues = await world.github.list_issues_by_label("hydraflow-test-helper")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])
        # #8986 — rollup shape: title names the (fake, kind) pair; the
        # uncovered helper names live in the body.
        assert "FakeDocker" in issue.title
        assert "test helpers" in issue.title
        assert "script_run" in issue.body
        assert "hydraflow-test-helper" in issue.labels
        assert "hydraflow-fake-coverage-gap" in issue.labels
        assert "hydraflow-find" in issue.labels

    async def test_unregistered_fake_files_no_adapter_gap(self, tmp_path) -> None:
        """A fake absent from _FAKE_TO_CASSETTE_DIR (no recordable cassette
        surface) must not produce an adapter-surface gap — no cassette-root
        fallback flagging every public method (auditor right-sizing)."""
        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        # FakeBeads is not a cassette-capable adapter (no recorder/cassette dir).
        (fake_dir / "fake_beads.py").write_text(
            "class FakeBeads:\n"
            "    async def claim(self, n): ...\n"
            "    async def close(self, n): ...\n"
        )
        # A real github cassette dir exists; pre-fix this is what the root
        # fallback scanned, flagging FakeBeads.claim/close as "uncovered".
        (repo / "tests" / "trust" / "contracts" / "cassettes" / "github").mkdir(
            parents=True
        )

        _seed_ports(
            world,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=True),
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert (
            await world.github.list_issues_by_label("hydraflow-adapter-surface") == []
        )
        assert (
            await world.github.list_issues_by_label("hydraflow-fake-coverage-gap") == []
        )

    async def test_recovered_surface_gap_autocloses_rollup(self, tmp_path) -> None:
        """#9541: when the last uncovered method gains a cassette, the loop
        closes its OWN rollup issue on the recovery tick instead of leaving
        it open for a human (mirrors the #10015 resolve-on-clean-tick shape).

        Needs a REAL StateTracker/DedupStore seeded as the auditor's state
        ports so tick 2 sees tick 1's rollup tracking — the catalog default
        is a clean-slate MagicMock that forgets the filed issue number.
        """
        world = MockWorld(tmp_path)

        repo = tmp_path / "repo"
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_github.py").write_text(
            "class FakeGitHub:\n    async def close_issue(self, num): ...\n"
        )
        cassettes = repo / "tests" / "trust" / "contracts" / "cassettes" / "github"
        cassettes.mkdir(parents=True)

        _seed_ports(
            world,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=True),
            fake_coverage_state=StateTracker(tmp_path / "auditor-state.json"),
            fake_coverage_dedup=DedupStore(
                "fake_coverage", tmp_path / "auditor-dedup.json"
            ),
        )

        # Tick 1 — close_issue has no cassette → one rollup filed, OPEN.
        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)
        open_issues = await world.github.list_issues_by_label(
            "hydraflow-adapter-surface"
        )
        assert len(open_issues) == 1
        number = open_issues[0]["number"]

        # The gap recovers: the missing cassette lands between ticks.
        (cassettes / "close_issue.yaml").write_text(
            yaml.safe_dump({"input": {"command": "close_issue"}, "output": {}})
        )

        # Tick 2 — full recovery auto-closes the rollup (#9541).
        stats = await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert stats["fake_coverage_auditor"]["rollups_closed"] == 1
        assert (
            await world.github.list_issues_by_label("hydraflow-adapter-surface") == []
        )
        issue = world.github.issue(number)
        assert issue.state == "closed"
        # Final body records the recovery trajectory, not a stale gap list.
        assert "~~`close_issue`~~" in issue.body
        # The resolution comment landed before the close.
        assert any("auto-clos" in c for c in issue.comments)
