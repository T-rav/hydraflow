"""Unit tests for the ``RepoWikiStore(read_only=True)`` guard (#9836)."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_wiki import RepoWikiReadOnlyError, RepoWikiStore, WikiEntry


def _entry() -> WikiEntry:
    return WikiEntry(
        title="An insight",
        content="Some body content.",
        topic="gotchas",
        source_type="plan",
        source_issue=7,
    )


def test_default_store_is_writable(tmp_path: Path) -> None:
    store = RepoWikiStore(tmp_path / "wiki")
    assert store.is_read_only is False
    # A content write succeeds and is observable via query.
    store.ingest("o/r", [_entry()])
    assert "An insight" in store.query("o/r")


def test_read_only_flag_reported(tmp_path: Path) -> None:
    assert RepoWikiStore(tmp_path / "wiki", read_only=True).is_read_only is True


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.ingest("o/r", [_entry()]),
        lambda s: s.write_entry("o/r", _entry(), topic="gotchas"),
        lambda s: s.mark_superseded("o/r", "x", superseded_by="y", reason="z"),
        lambda s: s.active_lint("o/r", closed_issues={7}),
    ],
)
def test_read_only_blocks_content_writes(tmp_path: Path, call) -> None:
    store = RepoWikiStore(tmp_path / "wiki", read_only=True)
    with pytest.raises(RepoWikiReadOnlyError):
        call(store)


def test_read_only_allows_reads_and_dedup_cache(tmp_path: Path) -> None:
    # Seed via a writable store, then reopen read-only over the same root.
    writable = RepoWikiStore(tmp_path / "wiki")
    writable.ingest("o/r", [_entry()])

    ro = RepoWikiStore(tmp_path / "wiki", read_only=True)
    assert "An insight" in ro.query("o/r")
    # Dedup bookkeeping is a gitignored cache, not knowledge content.
    assert ro.is_ingested("o/r", 7, "plan") is False
    ro.mark_ingested("o/r", 7, "plan")
    assert ro.is_ingested("o/r", 7, "plan") is True
