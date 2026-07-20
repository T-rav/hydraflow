"""Tests for reflection → wiki bridge in post_merge_handler.

Since #9836 the bridge no longer writes to the boot-time store (its roots
live under the operator's main checkout, and it is read-only). Instead it
enqueues each reflection as an ``ingest-entry`` maintenance task; the
``RepoWikiLoop`` applies them inside its ephemeral worktree so they ride
the maintenance PR. These tests assert the enqueue + clear contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from reflections import append_reflection, read_reflections
from repo_wiki import RepoWikiStore
from wiki_maint_queue import MaintenanceQueue, default_queue_path


def _config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    # enqueue_wiki_ingest resolves the shared queue via config.data_path;
    # the bound joinpath already accepts *parts, so no lambda is needed.
    cfg.data_path = tmp_path.joinpath
    return cfg


def _queued(cfg: MagicMock) -> list:
    return MaintenanceQueue(path=default_queue_path(cfg)).peek()


def test_bridge_enqueues_reflections_and_clears(tmp_path: Path) -> None:
    from post_merge_handler import _bridge_reflections_to_wiki

    cfg = _config(tmp_path)
    store = RepoWikiStore(tmp_path / "wiki")
    compiler = AsyncMock()

    append_reflection(
        cfg,
        42,
        phase="plan",
        content="architecture: use DI for service modules",
    )
    assert read_reflections(cfg, 42)

    _bridge_reflections_to_wiki(
        config=cfg,
        issue_number=42,
        repo="acme/widget",
        store=store,
        compiler=compiler,
    )

    # The reflection was enqueued as an ingest-entry task, not written to
    # the (read-only) boot store — repo_root stays clean.
    tasks = _queued(cfg)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind == "ingest-entry"
    assert task.repo_slug == "acme/widget"
    body = task.params["entry"]["content"]
    assert "DI" in body or "service modules" in body

    # Reflections file was cleared after a successful enqueue.
    assert read_reflections(cfg, 42) == ""


def test_bridge_no_ops_when_reflections_empty(tmp_path: Path) -> None:
    from post_merge_handler import _bridge_reflections_to_wiki

    cfg = _config(tmp_path)
    store = RepoWikiStore(tmp_path / "wiki")

    _bridge_reflections_to_wiki(
        config=cfg,
        issue_number=99,
        repo="acme/widget",
        store=store,
        compiler=AsyncMock(),
    )

    assert _queued(cfg) == []


def test_bridge_no_ops_when_store_is_none(tmp_path: Path) -> None:
    from post_merge_handler import _bridge_reflections_to_wiki

    cfg = _config(tmp_path)
    append_reflection(cfg, 42, phase="plan", content="irrelevant")

    _bridge_reflections_to_wiki(
        config=cfg,
        issue_number=42,
        repo="acme/widget",
        store=None,
        compiler=None,
    )

    # No enqueue and the log is kept (we did not promote it).
    assert _queued(cfg) == []
    assert "irrelevant" in read_reflections(cfg, 42)


def test_bridge_enqueues_every_reflection_block(tmp_path: Path) -> None:
    """Contradiction resolution is deferred to the loop's compile/drift
    passes now — the bridge just enqueues each reflection block."""
    from post_merge_handler import _bridge_reflections_to_wiki

    cfg = _config(tmp_path)
    store = RepoWikiStore(tmp_path / "wiki")

    append_reflection(
        cfg,
        7,
        phase="plan",
        content="architecture: always use Pydantic BaseModel for config.",
    )
    append_reflection(
        cfg,
        7,
        phase="review",
        content="architecture: prefer dataclasses over Pydantic for config.",
    )

    _bridge_reflections_to_wiki(
        config=cfg,
        issue_number=7,
        repo="acme/widget",
        store=store,
        compiler=AsyncMock(),
    )

    tasks = _queued(cfg)
    assert len(tasks) == 2
    bodies = " ".join(t.params["entry"]["content"] for t in tasks)
    assert "Pydantic" in bodies
    assert "dataclasses" in bodies
