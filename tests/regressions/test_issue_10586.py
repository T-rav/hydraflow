"""Regression guard for #10586 — WikiRotDetectorLoop never scanned the
tracked ``repo_wiki/`` per-entry layout, so per-entry shipped claims went
unverified.

``WikiRotDetectorLoop._load_wiki_entries`` walked ``RepoWikiStore.repo_dir(slug)``,
which for the self slug resolves to the flat ``wiki_root`` (``docs/wiki/``).
The tracked per-entry layout under ``{repo_root}/repo_wiki/{owner}/{repo}/{topic}/*.md``
is a *separate* ``tracked_root`` that was never walked. As a result a
``fixed_in_pr`` / ``code_refs`` shipped-claim marker written into a tracked
per-entry file (e.g. ``repo_wiki/T-rav/hydraflow/gotchas/0841-*.md``) was
invisible to the shipped-claim pass until ``WikiCompiler.compile_topic_tracked``
promoted the content into the flat topic page — and the LLM synthesis is not
guaranteed to carry the marker through.

Fix: the detector also scans the tracked layout for entries carrying a
shipped claim and runs the existing corroboration logic against them. Scoped
to the shipped-claim pass only (not the full per-cite pass) so a naive scan
over the ~400 active tracked entries cannot produce an issue-filing storm —
see the issue's blast-radius note.

This module asserts:
- a tracked-layout entry whose ``fixed_in_pr`` claim has only dead
  ``code_refs`` IS now detected (one entry-level shipped finding is filed);
- a tracked-layout entry whose claim has a live ``code_ref`` is NOT flagged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop

_SLUG = "hydra/hydraflow"


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _make_loop(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo=_SLUG)
    cfg.repo_root = tmp_path  # type: ignore[misc]

    state = MagicMock()
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = MagicMock()
    dedup.get.return_value = set()

    # An EMPTY flat wiki dir: the flat/compiled scan must yield nothing so the
    # only findings can come from the tracked-layout scan under test.
    flat_dir = tmp_path / "docs" / "wiki"
    flat_dir.mkdir(parents=True)
    wiki_store = MagicMock()
    wiki_store.repo_dir.return_value = flat_dir
    wiki_store.list_repos.return_value = [_SLUG]

    loop = WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=_deps(asyncio.Event()),
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    return loop, pr


def _write_tracked_entry(
    tmp_path: Path,
    *,
    entry_id: str,
    topic: str,
    fixed_in_pr: str,
    code_refs: str,
    title: str,
) -> Path:
    """Write a tracked per-entry markdown file (YAML frontmatter + body)
    carrying a shipped claim under ``{repo_root}/repo_wiki/{slug}/{topic}/``.
    """
    topic_dir = tmp_path / "repo_wiki" / _SLUG / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    path = topic_dir / f"{entry_id}-issue-6295-{topic}-shipped.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        "source_issue: 6295\n"
        "source_phase: review\n"
        "created_at: 2026-07-25T06:08:03.278827+00:00\n"
        "status: active\n"
        "corroborations: 1\n"
        f"fixed_in_pr: {fixed_in_pr}\n"
        f"code_refs: {code_refs}\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        "Prose describing the shipped fix.\n",
        encoding="utf-8",
    )
    return path


async def test_tracked_layout_shipped_claim_with_dead_refs_is_detected(
    tmp_path: Path,
) -> None:
    """A tracked per-entry file whose ``fixed_in_pr`` claim's ``code_refs`` no
    longer resolve at HEAD must file exactly one shipped-claim finding — the
    tracked layout was previously never scanned, so this drift was silent.
    """
    loop, pr = _make_loop(tmp_path)
    _write_tracked_entry(
        tmp_path,
        entry_id="0841",
        topic="gotchas",
        fixed_in_pr="#8715",
        code_refs="src/gone.py:vanished",
        title="Tracked shipped claim gone",
    )
    (tmp_path / "src").mkdir(exist_ok=True)  # module absent → code_ref dead

    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    pr.create_issue.assert_awaited_once()
    title, body, labels = pr.create_issue.await_args.args
    assert "#8715" in title
    assert "#8715" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_tracked_layout_shipped_claim_with_live_ref_is_not_flagged(
    tmp_path: Path,
) -> None:
    """A tracked per-entry file whose ``fixed_in_pr`` claim has at least one
    resolving ``code_ref`` is corroborated and must NOT fire.
    """
    loop, pr = _make_loop(tmp_path)
    _write_tracked_entry(
        tmp_path,
        entry_id="0842",
        topic="gotchas",
        fixed_in_pr="#8713",
        code_refs="src/live.py:present",
        title="Tracked shipped claim live",
    )
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "live.py").write_text("def present():\n    return 1\n")

    stats = await loop._do_work()

    assert stats["issues_filed"] == 0, stats
    pr.create_issue.assert_not_awaited()


async def test_tracked_layout_entry_without_shipped_claim_is_not_scanned(
    tmp_path: Path,
) -> None:
    """A tracked entry that carries no ``fixed_in_pr`` marker must be ignored
    by the tracked scan — this keeps the fix scoped to shipped-claim
    verification and prevents an issue-filing storm over the ~400 active
    tracked entries whose broken cites are out of scope for #10586.
    """
    loop, pr = _make_loop(tmp_path)
    topic_dir = tmp_path / "repo_wiki" / _SLUG / "gotchas"
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "0843-issue-6295-gotchas-plain.md").write_text(
        "---\n"
        "id: 0843\n"
        "topic: gotchas\n"
        "source_issue: 6295\n"
        "source_phase: review\n"
        "created_at: 2026-07-25T06:08:03.278827+00:00\n"
        "status: active\n"
        "corroborations: 1\n"
        "---\n"
        "\n"
        "# Plain entry citing src/gone.py:vanished\n"
        "\n"
        "See src/gone.py:vanished for the guard.\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(exist_ok=True)

    stats = await loop._do_work()

    assert stats["issues_filed"] == 0, stats
    pr.create_issue.assert_not_awaited()


@pytest.mark.parametrize("status", ["stale", "superseded"])
async def test_tracked_layout_inactive_shipped_claim_is_skipped(
    tmp_path: Path, status: str
) -> None:
    """Only ``status: active`` tracked entries are scanned — a stale or
    superseded entry on its way out must not fire even with a dead claim.
    """
    loop, pr = _make_loop(tmp_path)
    topic_dir = tmp_path / "repo_wiki" / _SLUG / "gotchas"
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "0844-issue-6295-gotchas-inactive.md").write_text(
        "---\n"
        "id: 0844\n"
        "topic: gotchas\n"
        "source_issue: 6295\n"
        "source_phase: review\n"
        "created_at: 2026-07-25T06:08:03.278827+00:00\n"
        f"status: {status}\n"
        "corroborations: 1\n"
        "fixed_in_pr: #8715\n"
        "code_refs: src/gone.py:vanished\n"
        "---\n"
        "\n"
        "# Inactive shipped claim\n"
        "\n"
        "Prose.\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(exist_ok=True)

    stats = await loop._do_work()

    assert stats["issues_filed"] == 0, stats
    pr.create_issue.assert_not_awaited()
