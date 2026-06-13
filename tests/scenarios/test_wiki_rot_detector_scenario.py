"""Scenario: WikiRotDetectorLoop fires on a seeded wiki with a broken cite.

Fabricates a one-entry wiki whose cite points at a real module but a
symbol that does not exist, exercises PRPort.list_closed_issues_by_label
via FakeGitHub (no raw subprocess), and asserts one ``hydraflow-find``
+ ``wiki-rot`` issue is filed via the bot's ``create_issue`` port.

Follows the F7 FlakeTracker (``eac5fc72``), S6 SkillPromptEval
(``93ebf387``), C6 FakeCoverageAuditor (``32b43ab0``), and rc-budget T9
(``20a4a177``) pattern: the catalog builder ``_build_wiki_rot_detector``
in ``tests/scenarios/catalog/loop_registrations.py`` reads pre-seeded
port keys (``wiki_rot_state`` / ``wiki_rot_dedup`` / ``wiki_store``) and
wires them into the constructor before the loop is instantiated.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

# ``ConfigFactory.create`` used by ``make_bg_loop_deps`` sets these defaults —
# the scenario seeds the wiki / source tree around them so the loop resolves
# its ``config.repo_root`` + ``config.repo`` against real files on disk.
_SLUG = "test-org/test-repo"
_REPO_SUBDIR = "repo"


def _seed_wiki(tmp_path: Path, slug: str) -> Path:
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    entry = wiki_dir / "patterns.md"
    entry.write_text(
        "# Patterns\n\n## RepoWikiStore guard\n\n"
        "The guard lives in `src/foo.py:bar` — see ADR-0099.\n"
    )
    return wiki_dir


def _seed_source(tmp_path: Path) -> None:
    """Seed ``repo_root/src/foo.py`` — ``make_bg_loop_deps`` sets
    ``config.repo_root = tmp_path / "repo"`` (see ``tests/helpers.py:175``).

    The file defines ``other()`` / ``Unrelated`` but not ``bar`` — AST
    verification misses the cite, and ``fuzzy_suggest`` returns ``other``
    from ``difflib.get_close_matches`` (cutoff 0.6 clears ``bar`` ↔
    ``other``).
    """
    repo_root = tmp_path / _REPO_SUBDIR
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "foo.py").write_text(
        "def other():\n    return 1\n\nclass Unrelated:\n    pass\n"
    )


class TestWikiRotDetectorScenario:
    """§4.9 — WikiRotDetector MockWorld scenario."""

    async def test_fires_on_broken_cite(
        self,
        tmp_path: Path,
    ) -> None:
        """Seeded broken cite ⇒ exactly one ``hydraflow-find`` + ``wiki-rot`` fire.

        AST verification against the seeded HydraFlow-self source tree
        resolves ``src/foo.py`` but not the symbol ``bar`` — the loop
        files a find with a ``Did you mean`` fuzzy suggestion and does
        **not** escalate (first attempt, below the 3-attempt threshold).
        """
        world = MockWorld(tmp_path)

        wiki_dir = _seed_wiki(tmp_path, _SLUG)
        _seed_source(tmp_path)

        fake_state = MagicMock()
        fake_state.get_wiki_rot_attempts.return_value = 0
        fake_state.inc_wiki_rot_attempts.return_value = 1

        fake_dedup = MagicMock()
        fake_dedup.get.return_value = set()

        fake_wiki_store = MagicMock()
        fake_wiki_store.list_repos.return_value = [_SLUG]
        fake_wiki_store.repo_dir.return_value = wiki_dir

        _seed_ports(
            world,
            wiki_rot_state=fake_state,
            wiki_rot_dedup=fake_dedup,
            wiki_store=fake_wiki_store,
        )

        stats = await world.run_with_loops(["wiki_rot_detector"], cycles=1)

        assert stats["wiki_rot_detector"]["status"] == "fired", stats
        assert stats["wiki_rot_detector"]["issues_filed"] >= 1, stats
        assert stats["wiki_rot_detector"]["escalations"] == 0, stats

        issues = await world.github.list_issues_by_label("wiki-rot")
        assert len(issues) == 1
        issue = world.github.issue(issues[0]["number"])

        assert "src/foo.py:bar" in issue.title
        assert "hydraflow-find" in issue.labels
        assert "wiki-rot" in issue.labels
        # Fuzzy suggestion surfaces — ``bar`` ↔ ``other`` via difflib 0.6 cutoff
        # OR the loop's first-symbol fallback when no close match clears.
        assert "Did you mean" in issue.body

    async def test_no_fire_when_cite_resolves(
        self,
        tmp_path: Path,
    ) -> None:
        """Cite pointing at a real symbol ⇒ no find filed, ``status=noop``."""
        world = MockWorld(tmp_path)

        wiki_dir = tmp_path / "wiki" / _SLUG
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "patterns.md").write_text(
            "# Patterns\n\nSee `src/foo.py:other` for the implementation.\n"
        )
        _seed_source(tmp_path)

        fake_state = MagicMock()
        fake_state.get_wiki_rot_attempts.return_value = 0
        fake_state.inc_wiki_rot_attempts.return_value = 1

        fake_dedup = MagicMock()
        fake_dedup.get.return_value = set()

        fake_wiki_store = MagicMock()
        fake_wiki_store.list_repos.return_value = [_SLUG]
        fake_wiki_store.repo_dir.return_value = wiki_dir

        _seed_ports(
            world,
            wiki_rot_state=fake_state,
            wiki_rot_dedup=fake_dedup,
            wiki_store=fake_wiki_store,
        )

        stats = await world.run_with_loops(["wiki_rot_detector"], cycles=1)

        assert stats["wiki_rot_detector"]["status"] == "noop", stats
        assert stats["wiki_rot_detector"]["issues_filed"] == 0, stats
        assert await world.github.list_issues_by_label("wiki-rot") == []

    async def test_reconcile_clears_closed_escalation(
        self,
        tmp_path: Path,
    ) -> None:
        """Closed wiki-rot-stuck in FakeGitHub ⇒ dedup key cleared via PRPort."""
        world = MockWorld(tmp_path)
        slug = _SLUG

        # Seed a closed escalation issue through FakeGitHub so that
        # list_closed_issues_by_label returns it without any subprocess.
        escalation_title = f"Wiki rot stuck: {slug} cites missing src/foo.py:bar"
        world.github.add_issue(
            901,
            escalation_title,
            f"Repo: `{slug}`",
            labels=["hitl-escalation", "wiki-rot-stuck"],
        )
        world.github._issues[901].state = "closed"

        dedup_key = f"wiki_rot_detector:{slug}:src/foo.py:bar"
        fake_dedup = MagicMock()
        fake_dedup.get.return_value = {dedup_key}

        fake_state = MagicMock()
        fake_state.get_wiki_rot_attempts.return_value = 0
        fake_state.inc_wiki_rot_attempts.return_value = 1

        fake_wiki_store = MagicMock()
        fake_wiki_store.list_repos.return_value = []  # no wiki scanning, just reconcile

        _seed_ports(
            world,
            wiki_rot_state=fake_state,
            wiki_rot_dedup=fake_dedup,
            wiki_store=fake_wiki_store,
        )

        await world.run_with_loops(["wiki_rot_detector"], cycles=1)

        fake_state.clear_wiki_rot_attempts.assert_any_call(f"{slug}:src/foo.py:bar")
        remaining_calls = [c.args[0] for c in fake_dedup.set_all.call_args_list]
        assert remaining_calls, (
            "dedup.set_all not invoked — reconcile should clear the key"
        )
        assert dedup_key not in remaining_calls[-1]
