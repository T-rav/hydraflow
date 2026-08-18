"""MockWorld scenario proving repo_wiki Phase 2/8 compilation is reachable (#11416).

Before this fix, ``_build_repo_wiki`` never forwarded a seeded
``wiki_compiler`` port, so ``self._wiki_compiler`` stayed ``None`` on every
catalog-built ``RepoWikiLoop`` and the guard at ``src/repo_wiki_loop.py:375``
short-circuited both the legacy ``compile_topic`` branch and the tracked
``compile_topic_tracked`` branch — no scenario run through
``world.run_with_loops(["repo_wiki"])`` could ever exercise topic
compilation, including the #11373 fingerprint gate.

The heal-and-open-PR machinery (git worktree, credentials, subprocess PR
creation) is orthogonal to this bug and is covered elsewhere (real-git e2e
in ``test_repo_wiki_loop_pr.py``; orchestration-reaches-heal in
``test_caretaker_loops_part2.py``'s L18). This scenario patches
``_heal_and_open_maintenance_pr`` the same way L18 does, but — unlike L18 —
lets the real compile phase run against a seeded tracked-layout topic, so
what's actually under test is: does a ``RepoWikiLoop`` built by
``run_with_loops(["repo_wiki"])`` have a live ``wiki_compiler``?
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler
from repo_wiki import DEFAULT_TOPICS
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports

pytestmark = pytest.mark.scenario_loops

_SLUG = "o/r"


def _write_active_tracked_entry(
    tracked_root: Path, slug: str, topic: str, *, entry_id: str, source_issue: int
) -> Path:
    topic_dir = tracked_root / slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"{source_issue:04d}-{entry_id}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        "status: active\n"
        "---\n"
        # A src/*.py anchor keeps wiki_anchor_gate.has_repo_anchor happy —
        # anchor-less entries get flagged stale by flag_generic_entries_stale
        # before the compile phase ever sees them (config default: on).
        "See `src/foo.py:Bar` for details.\n",
        encoding="utf-8",
    )
    return path


async def test_repo_wiki_scenario_reaches_tracked_compile_when_compiler_wired(
    tmp_path: Path,
) -> None:
    """A MockWorld run through run_with_loops(['repo_wiki']) now invokes
    compile_topic_tracked once wiki_compiler is seeded as a port."""
    from repo_wiki import RepoWikiStore

    topic = DEFAULT_TOPICS[0]
    tracked_root = tmp_path / "tracked_wiki"
    for i in range(5):
        _write_active_tracked_entry(
            tracked_root, _SLUG, topic, entry_id=f"e{i}", source_issue=i
        )
    store = RepoWikiStore(
        wiki_root=tmp_path / "wiki_root_unused",
        tracked_root=tracked_root,
        self_slug=None,
    )

    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = [_SLUG]

    compiler = FakeWikiCompiler()
    world = MockWorld(tmp_path)
    seed_ports(world, wiki_store=wiki_store, wiki_compiler=compiler)

    seen_compiler: dict[str, object] = {}

    async def _heal(self, closed_issues, stats):
        seen_compiler["value"] = self._wiki_compiler
        result = await self._lint_and_compile_repos(
            [_SLUG], tracked_root, closed_issues, store=store
        )
        stats.update(result)

    with patch("repo_wiki_loop.RepoWikiLoop._heal_and_open_maintenance_pr", _heal):
        await world.run_with_loops(["repo_wiki"], cycles=1)

    assert seen_compiler["value"] is compiler, (
        "RepoWikiLoop built via run_with_loops(['repo_wiki']) has no live "
        "wiki_compiler — Phase 2/8 compilation is unreachable"
    )
    assert compiler.compile_calls, (
        "compile_topic_tracked was never invoked — the wiki_compiler=None "
        "guard at src/repo_wiki_loop.py:375 is still short-circuiting "
        "Phase 8 even with a compiler seeded"
    )
    assert compiler.compile_calls[0].topic == topic
    assert compiler.compile_calls[0].repo == _SLUG


async def test_fingerprint_gate_skips_unchanged_topic_across_ticks(
    tmp_path: Path,
) -> None:
    """Multi-tick gate behaviour (#11373, audit finding #11409).

    The unit tests in ``tests/test_wiki_compile_state.py`` cover
    ``topic_fingerprint``/``WikiCompileState`` as pure functions, and
    ``tests/regressions/test_wiki_compile_churn_11373.py`` drives a
    MagicMock-wired loop. Neither exercises the gate the way production
    runs it: across separate ``_do_work()`` ticks, with the fingerprint
    computed from real on-disk entries and the decision round-tripped
    through ``wiki_compile_state.json`` on the config's data_root.

    Tick 1 compiles, tick 2 finds the topic byte-identical and skips the
    synthesis spawn, tick 3 sees mutated content and pays for it again.
    """
    from repo_wiki import RepoWikiStore

    topic = DEFAULT_TOPICS[0]
    tracked_root = tmp_path / "tracked_wiki"
    entries = [
        _write_active_tracked_entry(
            tracked_root, _SLUG, topic, entry_id=f"e{i}", source_issue=i
        )
        for i in range(5)
    ]
    store = RepoWikiStore(
        wiki_root=tmp_path / "wiki_root_unused",
        tracked_root=tracked_root,
        self_slug=None,
    )

    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = [_SLUG]

    compiler = FakeWikiCompiler()
    world = MockWorld(tmp_path)
    seed_ports(world, wiki_store=wiki_store, wiki_compiler=compiler)

    ticks = {"n": 0}
    calls_after_tick: list[int] = []

    async def _heal(self, closed_issues, stats):
        ticks["n"] += 1
        if ticks["n"] == 3:
            # Change the topic's content before the third tick's compile
            # phase — the gate must notice and re-spawn synthesis.
            entries[0].write_text(
                entries[0].read_text(encoding="utf-8")
                + "\nLater evidence: `src/foo.py:Baz`.\n",
                encoding="utf-8",
            )
        result = await self._lint_and_compile_repos(
            [_SLUG], tracked_root, closed_issues, store=store
        )
        stats.update(result)
        calls_after_tick.append(len(compiler.compile_calls))

    with patch("repo_wiki_loop.RepoWikiLoop._heal_and_open_maintenance_pr", _heal):
        await world.run_with_loops(["repo_wiki"], cycles=3)

    # Guard the instrument before reading it: a tick that never reached the
    # compile phase is indistinguishable from a tick the gate skipped, so a
    # throttled loop would make the assertion below vacuously green.
    assert ticks["n"] == 3, (
        f"only {ticks['n']} of 3 ticks reached the compile phase — the "
        "call-count assertion below cannot distinguish 'gate skipped it' "
        "from 'the tick never ran'"
    )
    assert calls_after_tick == [1, 1, 2], (
        "expected compile → skip → recompile across ticks, got cumulative "
        f"compile_topic_tracked counts {calls_after_tick}"
    )
