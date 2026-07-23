"""Ratchet + prune tests for the wiki repo-specificity gate (#9954).

Two behaviors are pinned here so they can't silently regress:

1. **Synthesis-time gate** — ``WikiCompiler.compile_topic_tracked`` /
   ``compile_topic`` drop anchor-less platitudes before they are written
   as ``issue-synthesis-*`` entries, and keep originals when the gate
   empties the batch.
2. **Prune pass** — ``flag_generic_entries_stale`` marks existing
   anchor-less active entries stale (mark-only) while leaving anchored
   ones active.

The synthesis prompts are also asserted to carry the repo-specificity
requirement so the LLM is steered, not only post-filtered.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from knowledge_metrics import metrics
from repo_wiki import RepoWikiStore, flag_generic_entries_stale
from wiki_anchor_gate import config_field_vocabulary
from wiki_compiler import (
    _COMPILE_TOPIC_PROMPT,
    _SYNTHESIZE_INGEST_PROMPT,
    WikiCompiler,
)

REPO = "acme/widget"

# A real platitude from the issue and a real anchored gotcha, as the LLM
# would emit them in a synthesis JSON array.
_PLATITUDE = {
    "title": "Use is None and is not None for optional sentinels",
    "content": (
        "Use `is None` for optional objects. Avoid `==` for sentinels; "
        "custom `__eq__` can hide bugs. **Why:** identity checks are safe."
    ),
    "source_type": "synthesis",
}
_ANCHORED = {
    "title": "RepoWikiLoop maintenance PRs coalesce on one branch",
    "content": (
        "Subsequent ticks append to the same branch when "
        "`repo_wiki_maintenance_pr_coalesce` is true. **Why:** avoids "
        "duplicate maintenance PRs."
    ),
    "source_type": "synthesis",
}


def _write_entry_file(
    path: Path,
    *,
    entry_id: str,
    topic: str = "gotchas",
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


def _compiler() -> WikiCompiler:
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._credentials = MagicMock()
    compiler._credentials.gh_token = ""
    compiler._runner = MagicMock()
    return compiler


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


class TestSynthesisPromptGrounding:
    def test_compile_prompt_requires_repo_anchor(self) -> None:
        assert "Repo-specificity requirement" in _COMPILE_TOPIC_PROMPT
        assert "ADR-0042" in _COMPILE_TOPIC_PROMPT
        assert "rc_cadence_hours" in _COMPILE_TOPIC_PROMPT

    def test_ingest_prompt_requires_repo_anchor(self) -> None:
        assert "Repo-specificity requirement" in _SYNTHESIZE_INGEST_PROMPT


class TestFilterAnchoredEntries:
    def test_platitude_dropped_anchored_kept(self) -> None:
        entries = WikiCompiler._parse_entries(json.dumps([_PLATITUDE, _ANCHORED]))
        kept = WikiCompiler._filter_anchored_entries(
            entries, repo=REPO, topic="gotchas", context="test"
        )
        assert [e.title for e in kept] == [_ANCHORED["title"]]
        assert metrics.snapshot()["wiki_entries_rejected_no_anchor"] == 1


class TestCompileTopicTrackedGate:
    def _seed(self, tmp_path: Path) -> Path:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        for i in range(3):
            _write_entry_file(
                topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md",
                entry_id=f"000{i + 1}",
                source_issue=i + 1,
                title=f"Original {i + 1}",
            )
        return tracked_root

    @pytest.mark.asyncio
    async def test_drops_platitude_keeps_anchored(self, tmp_path: Path) -> None:
        tracked_root = self._seed(tmp_path)
        compiler = _compiler()
        compiler._call_model = AsyncMock(
            return_value=json.dumps([_PLATITUDE, _ANCHORED])
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "gotchas")

        # Only the anchored entry survives the gate.
        assert count == 1
        topic_dir = tracked_root / REPO / "gotchas"
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        assert len(synthesis) == 1
        text = synthesis[0].read_text()
        assert "RepoWikiLoop" in text
        assert "optional sentinels" not in text
        assert metrics.snapshot()["wiki_entries_rejected_no_anchor"] == 1
        # Inputs are superseded because at least one anchored entry landed.
        for i in range(3):
            assert (
                "status: superseded"
                in (topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md").read_text()
            )

    @pytest.mark.asyncio
    async def test_all_platitudes_keeps_originals(self, tmp_path: Path) -> None:
        tracked_root = self._seed(tmp_path)
        compiler = _compiler()
        compiler._call_model = AsyncMock(
            return_value=json.dumps([_PLATITUDE, dict(_PLATITUDE, title="Another one")])
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "gotchas")

        assert count == 0
        topic_dir = tracked_root / REPO / "gotchas"
        assert list(topic_dir.glob("*-issue-synthesis-*.md")) == []
        # Fail-safe: originals stay active — never superseded by nothing.
        for i in range(3):
            assert (
                "status: active"
                in (topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md").read_text()
            )


class TestFlagGenericEntriesStale:
    def test_marks_anchorless_stale_leaves_anchored_active(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        _write_entry_file(
            topic_dir / "0001-issue-synthesis-platitude.md",
            entry_id="0001",
            title="Use is None for optional sentinels",
            body="Avoid `==` for sentinels. **Why:** identity is safe.",
        )
        _write_entry_file(
            topic_dir / "0002-issue-synthesis-anchored.md",
            entry_id="0002",
            title="RepoWikiLoop coalesces maintenance PRs",
            body="Uses `repo_wiki_maintenance_pr_coalesce`. **Why:** dedup.",
        )

        flagged = flag_generic_entries_stale(
            tracked_root, REPO, anchor_vocabulary=config_field_vocabulary()
        )

        assert flagged == 1
        platitude = (topic_dir / "0001-issue-synthesis-platitude.md").read_text()
        anchored = (topic_dir / "0002-issue-synthesis-anchored.md").read_text()
        assert "status: stale" in platitude
        assert "no repo-specific anchor" in platitude
        assert "status: active" in anchored

    def test_mark_only_never_deletes(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        path = topic_dir / "0001-issue-synthesis-platitude.md"
        _write_entry_file(
            path,
            entry_id="0001",
            title="Delete code blocks bottom-to-top",
            body="Edit from the last line upward. **Why:** line numbers shift.",
        )

        flag_generic_entries_stale(
            tracked_root, REPO, anchor_vocabulary=config_field_vocabulary()
        )

        assert path.exists()

    def test_noop_without_vocabulary(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        path = topic_dir / "0001-issue-synthesis-platitude.md"
        _write_entry_file(
            path, entry_id="0001", title="Generic tip", body="Do the thing."
        )

        assert flag_generic_entries_stale(tracked_root, REPO) == 0
        assert "status: active" in path.read_text()

    def test_idempotent_second_pass_flags_nothing(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        _write_entry_file(
            topic_dir / "0001-issue-synthesis-platitude.md",
            entry_id="0001",
            title="Generic best practice",
            body="Do the thing well. **Why:** quality.",
        )
        vocab = config_field_vocabulary()

        assert (
            flag_generic_entries_stale(tracked_root, REPO, anchor_vocabulary=vocab) == 1
        )
        # Already stale → not re-flagged.
        assert (
            flag_generic_entries_stale(tracked_root, REPO, anchor_vocabulary=vocab) == 0
        )


class TestRepoWikiStoreInjectionFavorsAnchored:
    """After the prune pass, stale platitudes drop out of prompt injection."""

    def test_query_excludes_flagged_entries(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        wiki_root = tmp_path / "wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        _write_entry_file(
            topic_dir / "0001-issue-synthesis-platitude.md",
            entry_id="0001",
            title="Use is None for optional sentinels",
            body="Avoid `==`. **Why:** identity is safe.",
        )
        _write_entry_file(
            topic_dir / "0002-issue-synthesis-anchored.md",
            entry_id="0002",
            title="WorkspacePort owns git reads",
            body="Route git reads through WorkspacePort. **Why:** air-gap.",
        )
        store = RepoWikiStore(wiki_root, tracked_root=tracked_root)

        before = store.query(REPO, topics=["gotchas"])
        assert "optional sentinels" in before

        flag_generic_entries_stale(
            tracked_root, REPO, anchor_vocabulary=config_field_vocabulary()
        )

        after = store.query(REPO, topics=["gotchas"])
        assert "optional sentinels" not in after
        assert "WorkspacePort" in after
