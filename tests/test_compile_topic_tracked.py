"""Tests for ``WikiCompiler.compile_topic_tracked`` and its helpers.

Phase 8 — reads tracked per-entry files, calls the LLM, writes a
synthesis per-entry file, and marks every input ``superseded`` so the
next ``RepoWikiLoop`` tick emits a ``chore(wiki): maintenance`` PR
with both the new synthesis entry and the updated statuses.

Tests cover the tracked-layout helpers directly plus the compiler
method with a stubbed ``_call_model`` so the suite never touches the
real LLM backend.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import (
    RepoWikiStore,
    WikiEntry,
    _load_tracked_active_entries,
    _mark_tracked_entry_superseded,
    _write_tracked_synthesis_entry,
)
from wiki_compiler import WikiCompiler

REPO = "acme/widget"


def _write_entry_file(
    path: Path,
    *,
    entry_id: str,
    topic: str,
    status: str = "active",
    source_issue: str | int = 1,
    title: str = "Existing entry",
    body: str = "Content body.",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: plan\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        "\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


class TestLoadTrackedActiveEntries:
    def test_returns_only_active(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "topic"
        _write_entry_file(
            topic_dir / "0001-issue-1-a.md",
            entry_id="0001",
            topic="patterns",
            title="A",
        )
        _write_entry_file(
            topic_dir / "0002-issue-2-b.md",
            entry_id="0002",
            topic="patterns",
            status="stale",
            title="B",
        )
        _write_entry_file(
            topic_dir / "0003-issue-3-c.md",
            entry_id="0003",
            topic="patterns",
            status="superseded",
            title="C",
        )

        entries = _load_tracked_active_entries(topic_dir)

        ids = [e["id"] for e in entries]
        assert ids == ["0001"]
        assert entries[0]["title"] == "A"

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _load_tracked_active_entries(tmp_path / "missing") == []

    def test_skips_files_without_frontmatter(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "topic"
        topic_dir.mkdir()
        (topic_dir / "0001-issue-1-x.md").write_text("# no frontmatter\n")
        assert _load_tracked_active_entries(topic_dir) == []


class TestMalformedTrackedEntryLogging:
    """Malformed tracked entries must not produce a per-entry WARNING storm.

    A non-numeric ``source_issue`` makes ``int(...)`` raise inside
    ``_load_tracked_topic_entries_with_paths``. The parser re-reads the same
    files every loop tick, so per-entry WARNINGs self-amplified to ~7,663
    lines/run in prod. The fix downgrades each skip to DEBUG (with the
    offending id) and emits exactly one aggregated WARNING per topic dir.
    """

    def _write_topic(self, tmp_path: Path) -> Path:
        topic_dir = tmp_path / "patterns"
        # One good entry plus two malformed (non-numeric source_issue).
        _write_entry_file(
            topic_dir / "0001-issue-1-good.md",
            entry_id="0001",
            topic="patterns",
            source_issue=1,
            title="Good",
        )
        _write_entry_file(
            topic_dir / "0002-issue-bad-b.md",
            entry_id="0002",
            topic="patterns",
            source_issue="not-a-number",
            title="Bad B",
        )
        _write_entry_file(
            topic_dir / "0003-issue-bad-c.md",
            entry_id="0003",
            topic="patterns",
            source_issue="also-bad",
            title="Bad C",
        )
        return topic_dir

    def test_per_entry_skip_logs_at_debug_with_id(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        topic_dir = self._write_topic(tmp_path)
        store = RepoWikiStore(tmp_path / "wikiroot")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.repo_wiki"):
            pairs = store._load_tracked_topic_entries_with_paths(topic_dir)

        # Good entry still parses; malformed ones are dropped (behavior intact).
        assert [entry.id for entry, _ in pairs] == ["0001"]

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        debug_msgs = [r.getMessage() for r in debug_records]
        assert any("0002" in m for m in debug_msgs)
        assert any("0003" in m for m in debug_msgs)
        assert all("malformed tracked entry" in m for m in debug_msgs)

    def test_emits_exactly_one_aggregated_warning_with_count_and_ids(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        topic_dir = self._write_topic(tmp_path)
        store = RepoWikiStore(tmp_path / "wikiroot")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.repo_wiki"):
            store._load_tracked_topic_entries_with_paths(topic_dir)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "skipped 2 malformed entries" in msg
        assert str(topic_dir) in msg
        assert "0002" in msg and "0003" in msg

    def test_no_warning_when_all_entries_well_formed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        topic_dir = tmp_path / "patterns"
        _write_entry_file(
            topic_dir / "0001-issue-1-good.md",
            entry_id="0001",
            topic="patterns",
            source_issue=1,
            title="Good",
        )
        store = RepoWikiStore(tmp_path / "wikiroot")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.repo_wiki"):
            pairs = store._load_tracked_topic_entries_with_paths(topic_dir)

        assert [entry.id for entry, _ in pairs] == ["0001"]
        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


class TestWriteTrackedSynthesisEntry:
    def test_writes_file_with_expected_frontmatter(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "patterns"
        entry = WikiEntry(
            title="Consolidated insight",
            content="Merged content.",
            source_type="synthesis",
            source_issue=None,
        )

        path = _write_tracked_synthesis_entry(
            topic_dir,
            entry=entry,
            topic="patterns",
            supersedes=["0001", "0002", "0003"],
        )

        assert path.exists()
        text = path.read_text()
        assert "source_phase: synthesis" in text
        assert "source_issue: synthesis" in text
        assert "supersedes: 0001,0002,0003" in text
        assert "# Consolidated insight" in text
        assert "issue-synthesis" in path.name

    def test_id_is_monotonic_within_topic(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "patterns"
        _write_entry_file(
            topic_dir / "0001-issue-1-prior.md",
            entry_id="0001",
            topic="patterns",
            title="prior",
        )

        path = _write_tracked_synthesis_entry(
            topic_dir,
            entry=WikiEntry(
                title="merged",
                content="merged body",
                source_type="synthesis",
                source_issue=None,
            ),
            topic="patterns",
            supersedes=["0001"],
        )
        assert path.name.startswith("0002-")


class TestMarkTrackedEntrySuperseded:
    def test_flips_status_and_adds_pointer(self, tmp_path: Path) -> None:
        entry_path = tmp_path / "0001-issue-1-x.md"
        _write_entry_file(entry_path, entry_id="0001", topic="patterns", title="X")

        _mark_tracked_entry_superseded(entry_path, superseded_by="0042")

        text = entry_path.read_text()
        assert "status: superseded" in text
        assert "superseded_by: 0042" in text

    def test_noop_when_no_frontmatter(self, tmp_path: Path) -> None:
        entry_path = tmp_path / "0001-bad.md"
        entry_path.write_text("just a markdown file\n")

        _mark_tracked_entry_superseded(entry_path, superseded_by="0042")

        # Left untouched.
        assert entry_path.read_text() == "just a markdown file\n"


class TestCompileTopicTracked:
    @pytest.fixture
    def compiler_with_active_entries(self, tmp_path: Path) -> tuple[WikiCompiler, Path]:
        """Build a WikiCompiler + seed 3 active entries in one topic."""
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "patterns"
        for i in range(3):
            _write_entry_file(
                topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md",
                entry_id=f"000{i + 1}",
                topic="patterns",
                source_issue=i + 1,
                title=f"Original {i + 1}",
            )

        compiler = WikiCompiler.__new__(WikiCompiler)
        compiler._config = MagicMock()
        compiler._config.wiki_compilation_tool = "stub"
        compiler._config.wiki_compilation_model = "stub"
        compiler._config.wiki_compilation_timeout = 60
        compiler._credentials = MagicMock()
        compiler._credentials.gh_token = ""
        compiler._runner = MagicMock()
        return compiler, tracked_root

    @pytest.mark.asyncio
    async def test_writes_synthesis_and_marks_inputs_superseded(
        self,
        compiler_with_active_entries: tuple[WikiCompiler, Path],
    ) -> None:
        compiler, tracked_root = compiler_with_active_entries

        compiler._call_model = AsyncMock(
            return_value='[{"title":"Merged","content":"Unified body.",'
            '"source_type":"synthesis"}]'
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

        assert count == 1
        topic_dir = tracked_root / REPO / "patterns"
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        assert len(synthesis) == 1
        synth_text = synthesis[0].read_text()
        assert "supersedes: 0001,0002,0003" in synth_text

        for i in range(3):
            original = topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md"
            assert "status: superseded" in original.read_text()

    @pytest.mark.asyncio
    async def test_skips_when_fewer_than_two_active_entries(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "patterns"
        _write_entry_file(
            topic_dir / "0001-issue-1-solo.md",
            entry_id="0001",
            topic="patterns",
            title="Solo",
        )

        compiler = WikiCompiler.__new__(WikiCompiler)
        compiler._config = MagicMock()
        compiler._credentials = MagicMock()
        compiler._credentials.gh_token = ""
        compiler._runner = MagicMock()
        compiler._call_model = AsyncMock(
            side_effect=AssertionError("should not be called")
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

        assert count == 0
        # Solo entry untouched.
        assert "status: active" in (topic_dir / "0001-issue-1-solo.md").read_text()

    @pytest.mark.asyncio
    async def test_model_failure_keeps_originals(
        self,
        compiler_with_active_entries: tuple[WikiCompiler, Path],
    ) -> None:
        compiler, tracked_root = compiler_with_active_entries

        # _call_model returning None simulates rc != 0 / timeout / parse fail.
        compiler._call_model = AsyncMock(return_value=None)

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

        assert count == 0
        topic_dir = tracked_root / REPO / "patterns"
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        assert synthesis == []
        # Originals stay active.
        for i in range(3):
            assert (
                "status: active"
                in (topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md").read_text()
            )

    @pytest.mark.asyncio
    async def test_llm_returned_no_entries_keeps_originals(
        self,
        compiler_with_active_entries: tuple[WikiCompiler, Path],
    ) -> None:
        compiler, tracked_root = compiler_with_active_entries

        # Valid JSON but empty list → no new entries, don't supersede.
        compiler._call_model = AsyncMock(return_value="[]")

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

        assert count == 0
        topic_dir = tracked_root / REPO / "patterns"
        for i in range(3):
            assert (
                "status: active"
                in (topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md").read_text()
            )
