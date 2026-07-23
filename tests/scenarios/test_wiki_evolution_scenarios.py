"""Release-gating scenarios for the wiki-evolution stack.

Covers the session's runtime-affecting PRs:

- **P5 #8400 (removed by #9836)** — the on-merge inline tracked compile
  (``_compile_tracked_topics_for_merge``) was deleted: it mutated
  ``repo_root/repo_wiki`` in the main checkout, but the maintenance PR is
  built in an ephemeral worktree, so those edits never committed and only
  dirtied the tree. Dedup now runs on the ``RepoWikiLoop`` cadence via the
  worktree-isolated PR.
- **P4 #8401 + B2 #8403** — ``RepoWikiLoop`` runs ``detect_drift``
  every tick, then ``apply_drift_markers`` flips entries citing
  missing files to ``status: stale``.

These scenarios use ``FakeWikiCompiler`` (in-memory call recorder)
and real tracked-layout filesystem state — the on-disk wiki format
is load-bearing for drift detection, so we exercise it end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def _write_tracked_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    entry_id: str,
    source_issue: int,
    status: str = "active",
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"{source_issue:04d}-{entry_id[-6:]}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# P5 — post-merge wiki compile: REMOVED by #9836. The inline on-merge
# tracked compile wrote to repo_root/repo_wiki (main checkout) but the
# maintenance PR is built in a worktree, so those edits never committed —
# they only dirtied the tree. Dedup now runs on the RepoWikiLoop cadence.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P4 + B2 — drift detection + auto-stale-marking
# ---------------------------------------------------------------------------


def test_drift_loop_flags_and_marks_missing_file_citation(tmp_path: Path) -> None:
    """End-to-end: seed wiki with a broken citation, run detect_drift
    and apply_drift_markers, verify the entry flipped to stale."""
    from wiki_drift_detector import apply_drift_markers, detect_drift

    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    entry_path = _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nLives in `src/deleted.py:LongGone`.",
        entry_id="01JF000000000000000001",
        source_issue=42,
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert "src/deleted.py" in finding.missing_files

    marked = apply_drift_markers(result.findings)
    assert marked == 1

    updated = entry_path.read_text(encoding="utf-8")
    assert "status: stale" in updated
    assert "stale_reason: drift_detected: src/deleted.py" in updated


def test_drift_loop_leaves_intact_entries_alone(tmp_path: Path) -> None:
    """Entries whose cited files still exist stay active, untouched."""
    from wiki_drift_detector import apply_drift_markers, detect_drift

    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "present.py").write_text("class ReallyHere:\n    pass\n")

    entry_path = _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="See `src/present.py:ReallyHere`.",
        entry_id="01JF000000000000000002",
        source_issue=43,
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    assert result.findings == []

    marked = apply_drift_markers(result.findings)
    assert marked == 0
    assert "status: active" in entry_path.read_text(encoding="utf-8")
