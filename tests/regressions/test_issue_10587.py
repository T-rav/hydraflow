"""Regression guard for #10587 — ``active_lint_tracked`` staled durable wiki
lessons purely because their *source issue closed*.

A tracked wiki lesson is durable knowledge. Its source issue closing is NOT
evidence the lesson is stale: a closed issue is the normal terminal state of a
fixed bug, and the gotcha it produced outlives the ticket. The pre-fix sweep
flipped any ``status: active`` tracked entry to ``stale`` the moment its
frontmatter ``source_issue`` appeared in the closed set, then pruned it after
90 days — retiring genuinely durable gotchas (e.g. the ``str.splitlines()``
C0-separator footgun from #10504) on a timer, racing ``WikiCompiler`` synthesis.

The fix exempts entries whose ``json:entry`` block carries a ``fixed_in_pr``
shipped claim that is *still corroborated* by live source (at least one
``code_ref`` resolves against the checked-out repo). Corroboration is the
lesson's own freshness/verification signal — driving staleness off it, not off
issue-closure. The exemption is narrow: a claim whose refs no longer resolve is
still swept (the sweep is narrowed, not disabled), and a plain coordination note
with no durability signal is still swept exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from repo_wiki import active_lint_tracked

REPO = "T-rav/hydraflow"
CLOSED_ISSUE = 10504


def _write_source(repo_root: Path, rel_path: str, symbol: str) -> None:
    """Write a trivial source module defining *symbol* so a ``code_ref`` of the
    form ``rel_path:symbol`` corroborates against ``repo_root``."""
    target = repo_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"def {symbol}(text):\n    return text\n", encoding="utf-8")


def _write_tracked_entry(
    tracked_root: Path,
    *,
    entry_id: str,
    topic: str,
    source_issue: int,
    created_at: str | None = None,
    json_entry: str | None = None,
) -> Path:
    """Write a ``status: active`` tracked per-entry markdown file and return its
    path. When *json_entry* is provided it is embedded as a ``json:entry``
    machine block in the body (the shipped-claim carrier)."""
    path = tracked_root / REPO / topic / f"{entry_id}-issue-{source_issue}-x.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = created_at or datetime.now(UTC).isoformat()
    body = f"# Entry {entry_id}\n\nDurable lesson body.\n"
    if json_entry is not None:
        body += f"\n```json:entry\n{json_entry}\n```\n"
    text = (
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: plan\n"
        f"created_at: {created}\n"
        "status: active\n"
        "---\n"
        "\n"
        f"{body}"
    )
    path.write_text(text, encoding="utf-8")
    return path


def test_durable_corroborated_lesson_survives_closed_source_issue(
    tmp_path: Path,
) -> None:
    """The #10504-style scenario: an active entry with a corroborated
    ``fixed_in_pr`` shipped claim whose source issue closed must NOT be staled,
    and its file bytes must be unchanged (no write at all)."""
    repo_root = tmp_path
    tracked_root = repo_root / "repo_wiki"
    _write_source(repo_root, "src/c0_marker.py", "split_markers")
    entry = _write_tracked_entry(
        tracked_root,
        entry_id="0841",
        topic="gotchas",
        source_issue=CLOSED_ISSUE,
        json_entry=(
            '{"fixed_in_pr": "#10505", "code_refs": ["src/c0_marker.py:split_markers"]}'
        ),
    )
    before = entry.read_bytes()

    result = active_lint_tracked(tracked_root, REPO, {CLOSED_ISSUE})

    assert entry.exists()
    assert entry.read_bytes() == before  # zero bytes written
    assert "status: active" in entry.read_text()
    assert result.entries_marked_stale == 0
    assert result.entries_exempt_shipped_claim == 1


def test_plain_coordination_note_still_staled_on_closed_issue(
    tmp_path: Path,
) -> None:
    """Control: an active entry with NO durability signal whose source issue
    closed is still swept stale exactly as before — the common case is
    unchanged."""
    repo_root = tmp_path
    tracked_root = repo_root / "repo_wiki"
    entry = _write_tracked_entry(
        tracked_root,
        entry_id="0002",
        topic="patterns",
        source_issue=CLOSED_ISSUE,
        json_entry=None,
    )

    result = active_lint_tracked(tracked_root, REPO, {CLOSED_ISSUE})

    assert "status: stale" in entry.read_text()
    assert result.entries_marked_stale == 1
    assert result.entries_exempt_shipped_claim == 0


def test_shipped_claim_with_dead_refs_is_still_staled(tmp_path: Path) -> None:
    """The exemption is narrow, not wholesale: a ``fixed_in_pr`` claim whose
    ``code_refs`` no longer resolve carries no live corroboration, so the entry
    is still swept stale."""
    repo_root = tmp_path
    tracked_root = repo_root / "repo_wiki"
    # Note: src/gone.py is never written — the ref is dead.
    entry = _write_tracked_entry(
        tracked_root,
        entry_id="0003",
        topic="gotchas",
        source_issue=CLOSED_ISSUE,
        json_entry='{"fixed_in_pr": "#10505", "code_refs": ["src/gone.py:vanished"]}',
    )

    result = active_lint_tracked(tracked_root, REPO, {CLOSED_ISSUE})

    assert "status: stale" in entry.read_text()
    assert result.entries_marked_stale == 1
    assert result.entries_exempt_shipped_claim == 0


def test_old_corroborated_lesson_not_pruned_same_pass(tmp_path: Path) -> None:
    """An entry past the 90-day prune window whose issue just closed is NOT
    flipped-then-pruned in the same pass when its shipped claim is
    corroborated: the exemption keeps it ``active`` so the prune branch is
    never reached."""
    repo_root = tmp_path
    tracked_root = repo_root / "repo_wiki"
    _write_source(repo_root, "src/c0_marker.py", "split_markers")
    long_ago = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    entry = _write_tracked_entry(
        tracked_root,
        entry_id="0841",
        topic="gotchas",
        source_issue=CLOSED_ISSUE,
        created_at=long_ago,
        json_entry=(
            '{"fixed_in_pr": "#10505", "code_refs": ["src/c0_marker.py:split_markers"]}'
        ),
    )

    result = active_lint_tracked(tracked_root, REPO, {CLOSED_ISSUE})

    assert entry.exists()
    assert "status: active" in entry.read_text()
    assert result.orphans_pruned == 0
    assert result.entries_exempt_shipped_claim == 1


def test_explicit_repo_root_resolves_refs(tmp_path: Path) -> None:
    """When ``repo_root`` is passed explicitly, corroboration resolves refs
    against it rather than ``tracked_root.parent`` — the wiring the loop uses to
    verify claims against the ephemeral worktree."""
    tracked_root = tmp_path / "wiki_store"  # deliberately NOT <repo_root>/repo_wiki
    repo_root = tmp_path / "checkout"
    _write_source(repo_root, "src/c0_marker.py", "split_markers")
    entry = _write_tracked_entry(
        tracked_root,
        entry_id="0841",
        topic="gotchas",
        source_issue=CLOSED_ISSUE,
        json_entry=(
            '{"fixed_in_pr": "#10505", "code_refs": ["src/c0_marker.py:split_markers"]}'
        ),
    )

    result = active_lint_tracked(
        tracked_root, REPO, {CLOSED_ISSUE}, repo_root=repo_root
    )

    assert "status: active" in entry.read_text()
    assert result.entries_exempt_shipped_claim == 1
