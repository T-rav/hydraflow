"""Regression: ``WikiCompiler.compile_topic_tracked`` must propagate
``fixed_in_pr`` / ``code_refs`` onto synthesized tracked entries (issue #10590).

When the compiler promotes tracked per-entry files into a synthesized
entry, the shipped-claim provenance markers (``fixed_in_pr`` /
``code_refs``) present on the source entries were dropped — the
synthesized entry relied on the LLM to echo them, which it doesn't
guarantee. Downstream shipped-claim verification
(``WikiRotDetectorLoop``) then can't tie the compiled entry back to its
PR/code, so the compiled page under-reports what the tracked entry
asserted.

Fix: the compiler deterministically unions the source entries'
``fixed_in_pr`` / ``code_refs`` onto the synthesized entry, and the
tracked read/write helpers round-trip those fields through frontmatter.

Supporting seams exercised here:
- ``RepoWikiStore.write_entry`` persists ``fixed_in_pr`` / ``code_refs``
  into tracked frontmatter (source side carries the provenance).
- ``_load_tracked_active_entries`` surfaces them back.
- ``_write_tracked_synthesis_entry`` persists them on the synthesis output.
- ``compile_topic_tracked`` unions across the superseded sources.

The #10573 byte-identity skip guard (``synthesis_matches_active_bodies``)
must NOT regress: it compares bodies only, so provenance in frontmatter
never suppresses a genuine synthesis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import (
    RepoWikiStore,
    WikiEntry,
    _load_tracked_active_entries,
    _write_tracked_synthesis_entry,
)
from wiki_compiler import WikiCompiler

REPO = "acme/widget"


def _write_source_entry(
    path: Path,
    *,
    entry_id: str,
    topic: str,
    source_issue: str | int,
    title: str,
    body: str,
    fixed_in_pr: str | None = None,
    code_refs: tuple[str, ...] = (),
) -> None:
    """Seed a ``status: active`` tracked per-entry file that carries
    optional shipped-claim provenance in frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    lines = [
        "---",
        f"id: {entry_id}",
        f"topic: {topic}",
        f"source_issue: {source_issue}",
        "source_phase: plan",
        f"created_at: {now}",
        "status: active",
        "corroborations: 1",
    ]
    if fixed_in_pr:
        lines.append(f"fixed_in_pr: {fixed_in_pr}")
    if code_refs:
        lines.append("code_refs: " + ",".join(code_refs))
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_compiler() -> WikiCompiler:
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._config.wiki_compilation_tool = "stub"
    compiler._config.wiki_compilation_model = "stub"
    compiler._config.wiki_compilation_timeout = 60
    compiler._credentials = MagicMock()
    compiler._credentials.gh_token = ""
    compiler._runner = MagicMock()
    return compiler


class TestLoadTrackedActiveEntriesSurfacesProvenance:
    def test_surfaces_fixed_in_pr_and_code_refs_from_frontmatter(
        self, tmp_path: Path
    ) -> None:
        topic_dir = tmp_path / "gotchas"
        _write_source_entry(
            topic_dir / "0001-issue-1-a.md",
            entry_id="0001",
            topic="gotchas",
            source_issue=1,
            title="A",
            body="Body A.",
            fixed_in_pr="#8713",
            code_refs=("src/a.py:Foo", "src/b.py:Bar"),
        )

        entries = _load_tracked_active_entries(topic_dir)

        assert entries[0]["fixed_in_pr"] == "#8713"
        assert entries[0]["code_refs"] == ("src/a.py:Foo", "src/b.py:Bar")

    def test_defaults_when_absent(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "gotchas"
        _write_source_entry(
            topic_dir / "0001-issue-1-a.md",
            entry_id="0001",
            topic="gotchas",
            source_issue=1,
            title="A",
            body="Body A.",
        )

        entries = _load_tracked_active_entries(topic_dir)

        assert entries[0]["fixed_in_pr"] is None
        assert entries[0]["code_refs"] == ()


class TestWriteEntryPersistsProvenance:
    def test_write_entry_round_trips_provenance_through_frontmatter(
        self, tmp_path: Path
    ) -> None:
        store = RepoWikiStore(
            wiki_root=tmp_path / "wikiroot",
            tracked_root=tmp_path / "repo_wiki",
        )
        entry = WikiEntry(
            title="Shipped gotcha",
            content="RepoWikiLoop drops provenance. See `src/repo_wiki.py`.",
            source_type="manual",
            source_issue=42,
            fixed_in_pr="#8713",
            code_refs=("src/repo_wiki.py:write_entry",),
        )

        path = store.write_entry(REPO, entry, topic="gotchas")

        text = path.read_text()
        assert "fixed_in_pr: #8713" in text
        assert "code_refs: src/repo_wiki.py:write_entry" in text

        loaded = _load_tracked_active_entries(path.parent)
        assert loaded[0]["fixed_in_pr"] == "#8713"
        assert loaded[0]["code_refs"] == ("src/repo_wiki.py:write_entry",)


class TestWriteTrackedSynthesisEntryPersistsProvenance:
    def test_synthesis_entry_carries_provenance(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "gotchas"
        entry = WikiEntry(
            title="Merged",
            content="RepoWikiLoop merged. See `src/repo_wiki.py`.",
            source_type="synthesis",
            source_issue=None,
            fixed_in_pr="#8713,#8720",
            code_refs=("src/a.py:Foo", "src/b.py:Bar"),
        )

        path = _write_tracked_synthesis_entry(
            topic_dir, entry=entry, topic="gotchas", supersedes=["0001", "0002"]
        )

        text = path.read_text()
        assert "fixed_in_pr: #8713,#8720" in text
        assert "code_refs: src/a.py:Foo,src/b.py:Bar" in text


class TestCompileTopicTrackedUnionsProvenance:
    @pytest.mark.asyncio
    async def test_synthesized_entry_unions_source_provenance(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        _write_source_entry(
            topic_dir / "0001-issue-1-a.md",
            entry_id="0001",
            topic="gotchas",
            source_issue=1,
            title="Source A",
            body="Body A.",
            fixed_in_pr="#8713",
            code_refs=("src/a.py:Foo",),
        )
        _write_source_entry(
            topic_dir / "0002-issue-2-b.md",
            entry_id="0002",
            topic="gotchas",
            source_issue=2,
            title="Source B",
            body="Body B.",
            fixed_in_pr="#8720",
            code_refs=("src/b.py:Bar", "src/a.py:Foo"),
        )

        compiler = _make_compiler()
        # Anchored, non-duplicate content so the #9954 anchor gate keeps it
        # and the #10573 byte-identity guard lets it through.
        compiler._call_model = AsyncMock(
            return_value='[{"title":"Merged insight","content":"RepoWikiLoop '
            'unifies these. See `src/repo_wiki.py`.","source_type":"synthesis"}]'
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "gotchas")

        assert count == 1
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        assert len(synthesis) == 1
        text = synthesis[0].read_text()
        # Union of both sources' fixed_in_pr (order-preserving, deduped).
        assert "fixed_in_pr: #8713,#8720" in text
        # Union of code_refs, deduped, order-preserving across sources.
        assert "code_refs: src/a.py:Foo,src/b.py:Bar" in text

    @pytest.mark.asyncio
    async def test_no_provenance_lines_when_sources_have_none(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        for i in range(2):
            _write_source_entry(
                topic_dir / f"000{i + 1}-issue-{i + 1}-x.md",
                entry_id=f"000{i + 1}",
                topic="gotchas",
                source_issue=i + 1,
                title=f"Source {i + 1}",
                body=f"Body {i + 1}.",
            )

        compiler = _make_compiler()
        compiler._call_model = AsyncMock(
            return_value='[{"title":"Merged insight","content":"RepoWikiLoop '
            'unifies these. See `src/repo_wiki.py`.","source_type":"synthesis"}]'
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "gotchas")

        assert count == 1
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        text = synthesis[0].read_text()
        assert "fixed_in_pr:" not in text
        assert "code_refs:" not in text
