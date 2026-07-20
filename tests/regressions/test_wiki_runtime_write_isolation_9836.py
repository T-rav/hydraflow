"""Regression #9836: runtime wiki writes must never dirty repo_root.

The boot-time ``RepoWikiStore`` (service_registry) is rooted under the
operator's main checkout: ``wiki_root = repo_root/docs/wiki`` and
``tracked_root = repo_root/repo_wiki``. Before this fix, several runtime
paths wrote knowledge content straight to that store —
``post_merge_handler`` (reflection bridge, shipped-with-known-gap) and the
plan/review ingest fallbacks — leaving the factory's checkout perpetually
dirty (operator stashed twice on 2026-07-18). #9539 only isolated the
maintenance heal, not these paths.

The fix makes the boot store ``read_only=True`` so knowledge-content
writes there raise instead of silently corrupting the tree, and routes the
runtime writers through the worktree-isolated maintenance PR (via the
``ingest-entry`` queue). Gitignored runtime caches (``ingest_dedup.json``,
``log.jsonl``, ``index.json``) remain writable — they never dirty the
tree.

This test constructs the boot store over a throwaway git repo, exercises
every runtime write surface, and asserts the tracked tree stays clean.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from repo_wiki import RepoWikiReadOnlyError, RepoWikiStore, WikiEntry
from wiki_maint_queue import MaintenanceQueue, default_queue_path, enqueue_wiki_ingest

SELF_SLUG = "owner/repo"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A committed git repo mirroring the self-repo wiki layout on disk."""
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tester")

    # Tracked self-repo wiki: flat topic pages under docs/wiki + a tracked
    # per-entry layout under repo_wiki/owner/repo.
    wiki = root / "docs" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "gotchas.md").write_text(
        "# Gotchas\n\n## Existing insight\nBody.\n\n"
        '```json:entry\n{"id":"01JEXISTING0000000000000","title":"Existing insight",'
        '"source_type":"manual","source_issue":1}\n```\n',
        encoding="utf-8",
    )
    (wiki / "index.md").write_text(
        "# Wiki Index: owner/repo\n\n**1 entries**\n", "utf-8"
    )

    tracked = root / "repo_wiki" / SELF_SLUG / "gotchas"
    tracked.mkdir(parents=True)
    (tracked / "0001-issue-1-existing.md").write_text(
        "---\nid: 0001\ntopic: gotchas\nsource_issue: 1\nsource_phase: implement\n"
        "created_at: 2026-01-01T00:00:00+00:00\nstatus: active\n---\n\n# Existing\n\nBody.\n",
        encoding="utf-8",
    )

    # Runtime caches are gitignored — writes to them must not dirty the tree.
    (root / ".gitignore").write_text(
        "docs/wiki/log.jsonl\ndocs/wiki/ingest_dedup.json\ndocs/wiki/index.json\n",
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed wiki")
    assert _porcelain(root) == ""
    return root


def _boot_store(repo_root: Path) -> RepoWikiStore:
    """Construct the store exactly as service_registry does at boot."""
    return RepoWikiStore(
        wiki_root=repo_root / "docs" / "wiki",
        tracked_root=repo_root / "repo_wiki",
        self_slug=SELF_SLUG,
        read_only=True,
    )


def _entry() -> WikiEntry:
    return WikiEntry(
        title="Runtime write that must not touch repo_root",
        content="This should never be written into the main checkout.",
        topic="gotchas",
        source_type="shipped-with-known-gap",
        source_issue=505,
        source_repo=SELF_SLUG,
    )


def test_boot_store_rejects_content_writes(repo_root: Path) -> None:
    store = _boot_store(repo_root)
    entry = _entry()

    with pytest.raises(RepoWikiReadOnlyError):
        store.ingest(SELF_SLUG, [entry])
    with pytest.raises(RepoWikiReadOnlyError):
        store.write_entry(SELF_SLUG, entry, topic="gotchas")
    with pytest.raises(RepoWikiReadOnlyError):
        store.mark_superseded(SELF_SLUG, "0001", superseded_by="x", reason="test")
    with pytest.raises(RepoWikiReadOnlyError):
        store.active_lint(SELF_SLUG, closed_issues={1})

    # Every rejected write left the tracked tree untouched.
    assert _porcelain(repo_root) == ""


def test_boot_store_allows_reads_and_gitignored_caches(repo_root: Path) -> None:
    store = _boot_store(repo_root)

    # Reads still work (agents consume wiki context at boot).
    assert "Existing" in store.query(SELF_SLUG)

    # Dedup bookkeeping is a gitignored runtime cache — allowed, and it
    # does not dirty the tracked tree.
    assert not store.is_ingested(SELF_SLUG, 505, "plan")
    store.mark_ingested(SELF_SLUG, 505, "plan")
    assert store.is_ingested(SELF_SLUG, 505, "plan")

    assert _porcelain(repo_root) == ""


def test_runtime_ingest_reroutes_to_queue_outside_repo_root(
    repo_root: Path, tmp_path: Path
) -> None:
    """The rerouted write lands in the gitignored data root, never repo_root."""
    data_root = tmp_path / "data"
    cfg = MagicMock()
    cfg.data_path = data_root.joinpath

    n = enqueue_wiki_ingest(cfg, SELF_SLUG, [_entry()])
    assert n == 1

    # The queue file is under the data root, not the checkout.
    queue_path = default_queue_path(cfg)
    assert data_root in queue_path.parents
    assert _porcelain(repo_root) == ""

    tasks = MaintenanceQueue(path=queue_path).peek()
    assert [t.kind for t in tasks] == ["ingest-entry"]
    assert tasks[0].params["entry"]["title"] == _entry().title
