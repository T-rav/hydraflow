"""Regression tests for issue #10573 — RepoWikiLoop synthesis re-emits
byte-identical entries every tick, growing ids without bound.

Every ``RepoWikiLoop`` maintenance tick calls
``WikiCompiler.compile_topic_tracked``; the LLM returns the *same* content,
yet the compiler unconditionally wrote N new synthesis per-entry files and
marked the N inputs ``superseded`` — even when the synthesized bodies were
byte-identical to the current active set. The observable damage (seen in
``repo_wiki/T-rav/hydraflow/dependencies/``: 0006 -> 0011 -> 0017, four of
five entries byte-identical across regenerations) is a permanently churning
maintenance PR, an ever-deepening supersession chain, and unbounded id
growth in every topic.

The fix adds a compiler-side byte-identity no-op guard: before writing any
synthesis entry, ``compile_topic_tracked`` compares the synthesized bodies
against the current active set (id-, timestamp- and order-agnostic,
multiplicity-preserving). If nothing changed it emits nothing — no new id,
no supersession. A genuine edit still synthesizes exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import (
    WikiEntry,
    _load_tracked_active_entries,
    synthesis_matches_active_bodies,
)
from wiki_compiler import WikiCompiler

REPO = "T-rav/hydraflow"

# Two anchored synthesis entries (name a module / loop so the #9954
# repo-anchor gate keeps them). The exact bodies are re-emitted verbatim on
# every tick — this is the churn the guard must suppress.
_SYNTH_JSON = (
    "["
    '{"title":"Alpha fact",'
    '"content":"RepoWikiLoop unifies these. See `src/repo_wiki.py`.",'
    '"source_type":"synthesis"},'
    '{"title":"Beta fact",'
    '"content":"Phase 8 synthesis lives in `src/repo_wiki_loop.py`.",'
    '"source_type":"synthesis"}'
    "]"
)


def _write_entry_file(
    path: Path,
    *,
    entry_id: str,
    title: str,
    body: str,
    status: str = "active",
    source_issue: str | int = 1,
    source_phase: str = "plan",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        "topic: dependencies\n"
        f"source_issue: {source_issue}\n"
        f"source_phase: {source_phase}\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        "\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def _make_compiler(call_model: AsyncMock) -> WikiCompiler:
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._config.wiki_compilation_tool = "stub"
    compiler._config.wiki_compilation_model = "stub"
    compiler._config.wiki_compilation_timeout = 60
    compiler._credentials = MagicMock()
    compiler._credentials.gh_token = ""
    compiler._runner = MagicMock()
    compiler._call_model = call_model
    return compiler


def _seed_two_ingest_entries(tracked_root: Path) -> Path:
    topic_dir = tracked_root / REPO / "dependencies"
    _write_entry_file(
        topic_dir / "0001-issue-1-orig.md",
        entry_id="0001",
        title="Original one",
        body="RepoWikiLoop does X. See `src/repo_wiki.py`.",
        source_issue=1,
    )
    _write_entry_file(
        topic_dir / "0002-issue-2-orig.md",
        entry_id="0002",
        title="Original two",
        body="Phase 8 does Y. See `src/repo_wiki_loop.py`.",
        source_issue=2,
    )
    return topic_dir


def _synthesis_files(topic_dir: Path) -> list[Path]:
    return sorted(topic_dir.glob("*-issue-synthesis-*.md"))


class TestByteIdenticalReEmitSkipped:
    """The core churn: repeated ticks over an unchanged active set must
    emit exactly one generation of synthesis entries — no id growth."""

    @pytest.mark.asyncio
    async def test_second_identical_tick_writes_no_new_entry(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = _seed_two_ingest_entries(tracked_root)
        compiler = _make_compiler(AsyncMock(return_value=_SYNTH_JSON))

        # Tick 1: two ingest entries -> two synthesis entries.
        first = await compiler.compile_topic_tracked(tracked_root, REPO, "dependencies")
        assert first == 2
        after_first = _synthesis_files(topic_dir)
        assert len(after_first) == 2

        # Tick 2: the active set is now those two synthesis entries and the
        # LLM re-emits identical bodies -> must be a no-op (no new ids).
        second = await compiler.compile_topic_tracked(
            tracked_root, REPO, "dependencies"
        )

        assert second == 0
        after_second = _synthesis_files(topic_dir)
        assert [p.name for p in after_second] == [p.name for p in after_first]
        # The prior synthesis entries stay active (not superseded by copies).
        active = _load_tracked_active_entries(topic_dir)
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_three_identical_ticks_keep_id_count_flat(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = _seed_two_ingest_entries(tracked_root)
        compiler = _make_compiler(AsyncMock(return_value=_SYNTH_JSON))

        await compiler.compile_topic_tracked(tracked_root, REPO, "dependencies")
        baseline = len(_synthesis_files(topic_dir))

        for _ in range(2):
            await compiler.compile_topic_tracked(tracked_root, REPO, "dependencies")

        assert len(_synthesis_files(topic_dir)) == baseline


class TestChangedContentStillSynthesizes:
    """A real edit between ticks must still produce a fresh synthesis."""

    @pytest.mark.asyncio
    async def test_edited_body_re_triggers_synthesis(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = _seed_two_ingest_entries(tracked_root)

        call_model = AsyncMock(return_value=_SYNTH_JSON)
        compiler = _make_compiler(call_model)
        assert (
            await compiler.compile_topic_tracked(tracked_root, REPO, "dependencies")
            == 2
        )
        before = len(_synthesis_files(topic_dir))

        # Second tick: the model returns genuinely different content.
        edited_json = (
            "["
            '{"title":"Alpha fact",'
            '"content":"RepoWikiLoop unifies these NOW. See `src/repo_wiki.py`.",'
            '"source_type":"synthesis"},'
            '{"title":"Beta fact",'
            '"content":"Phase 8 synthesis lives in `src/repo_wiki_loop.py`.",'
            '"source_type":"synthesis"}'
            "]"
        )
        call_model.return_value = edited_json

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "dependencies")

        assert count >= 1
        # New synthesis entries were written (id count grew).
        assert len(_synthesis_files(topic_dir)) > before


class TestSynthesisMatchesActiveBodies:
    """The pure comparison helper: id/timestamp/order-agnostic multiset."""

    @staticmethod
    def _active(body: str) -> dict[str, object]:
        return {"id": "irrelevant", "body": body}

    @staticmethod
    def _compiled(title: str, content: str) -> WikiEntry:
        return WikiEntry(title=title, content=content, source_type="synthesis")

    def test_identical_bodies_match_despite_ids_and_order(self) -> None:
        active = [
            self._active("# Alpha\n\nbody a"),
            self._active("# Beta\n\nbody b"),
        ]
        compiled = [
            self._compiled("Beta", "body b"),  # reversed order on purpose
            self._compiled("Alpha", "body a"),
        ]
        assert synthesis_matches_active_bodies(active, compiled) is True

    def test_added_entry_does_not_match(self) -> None:
        active = [self._active("# Alpha\n\nbody a")]
        compiled = [
            self._compiled("Alpha", "body a"),
            self._compiled("Gamma", "body c"),
        ]
        assert synthesis_matches_active_bodies(active, compiled) is False

    def test_edited_body_does_not_match(self) -> None:
        active = [self._active("# Alpha\n\nbody a")]
        compiled = [self._compiled("Alpha", "body a EDITED")]
        assert synthesis_matches_active_bodies(active, compiled) is False

    def test_multiplicity_is_preserved(self) -> None:
        # Two active copies of one body, but only one compiled -> differ.
        active = [
            self._active("# Alpha\n\nbody a"),
            self._active("# Alpha\n\nbody a"),
        ]
        compiled = [self._compiled("Alpha", "body a")]
        assert synthesis_matches_active_bodies(active, compiled) is False
