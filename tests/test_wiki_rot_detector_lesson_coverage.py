"""Continuous lesson-coverage gate in WikiRotDetectorLoop (#10763).

#10758's one-shot auditor triages the existing orphan backlog, but nothing
stops the next synthesis round from re-orphaning a lesson. This pass runs the
same lesson-survival tiering each cycle (self-repo only, dedup-guarded, under
the existing ADR-0049 kill-switch) and files a ``hydraflow-find`` when a
newly-orphaned lesson with live anchors appears.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop

SLUG = "T-rav/hydraflow"


def _deps(enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _make_loop(repo_root: Path, pr: AsyncMock) -> WikiRotDetectorLoop:
    cfg = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo=SLUG,
        repo_root=repo_root,
        repo_wiki_path="repo_wiki",
    )
    state = MagicMock()
    dedup = MagicMock()
    wiki_store = MagicMock()
    return WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=_deps(),
    )


def _write_entry(
    topic_dir: Path,
    *,
    entry_id: str,
    title: str,
    body: str = "",
    status: str = "active",
    superseded_by: str | None = None,
    supersedes: list[str] | None = None,
    code_refs: str | None = None,
) -> None:
    topic_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {entry_id}",
        f"topic: {topic_dir.name}",
        "source_issue: synthesis",
        "source_phase: synthesis",
        "created_at: 2026-01-01T00:00:00+00:00",
        f"status: {status}",
        "corroborations: 1",
    ]
    if superseded_by is not None:
        lines.append(f"superseded_by: {superseded_by}")
    if supersedes:
        lines.append("supersedes: " + ",".join(supersedes))
    if code_refs is not None:
        lines.append(f"code_refs: {code_refs}")
    lines += ["---", "", f"# {title}", "", body or f"Body for {entry_id}.", ""]
    slug = title.lower().replace(" ", "-")
    (topic_dir / f"{entry_id}-issue-synthesis-{slug}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _seed_orphan_corpus(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "detect.py").write_text(
        '_SHA_MARKER = "x"\n', encoding="utf-8"
    )
    gotchas = repo_root / "repo_wiki" / SLUG / "gotchas"
    _write_entry(
        gotchas,
        entry_id="0841",
        title="Marker splitlines bug",
        status="superseded",
        superseded_by="0851",
        code_refs="src/detect.py:_SHA_MARKER",
    )
    _write_entry(
        gotchas,
        entry_id="0851",
        title="Unrelated successor",
        status="active",
        supersedes=["0841"],
        body="Nothing about the marker here.",
    )


async def test_files_find_for_newly_orphaned_lesson(tmp_path: Path) -> None:
    _seed_orphan_corpus(tmp_path)
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=1)
    loop = _make_loop(tmp_path, pr)

    dedup_seen: set[str] = set()
    filed = await loop._file_lesson_coverage_finds(SLUG, tmp_path, dedup_seen)

    assert filed == 1
    pr.create_issue.assert_awaited_once()
    title = pr.create_issue.await_args.args[0]
    body = pr.create_issue.await_args.args[1]
    assert "0841" in title or "0841" in body
    assert "_SHA_MARKER" in body
    # A dedup key was recorded so the same orphan is not re-filed next cycle.
    assert any("0841" in key for key in dedup_seen)


async def test_dedup_suppresses_already_filed_orphan(tmp_path: Path) -> None:
    _seed_orphan_corpus(tmp_path)
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=1)
    loop = _make_loop(tmp_path, pr)

    dedup_seen: set[str] = set()
    await loop._file_lesson_coverage_finds(SLUG, tmp_path, dedup_seen)
    pr.create_issue.reset_mock()
    # Second cycle with the dedup key already present: no new issue.
    filed = await loop._file_lesson_coverage_finds(SLUG, tmp_path, dedup_seen)
    assert filed == 0
    pr.create_issue.assert_not_awaited()


async def test_represented_lesson_files_nothing(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "detect.py").write_text('_SHA_MARKER = "x"\n', encoding="utf-8")
    gotchas = tmp_path / "repo_wiki" / SLUG / "gotchas"
    _write_entry(
        gotchas,
        entry_id="0841",
        title="Marker splitlines bug",
        status="superseded",
        superseded_by="0851",
        code_refs="src/detect.py:_SHA_MARKER",
    )
    _write_entry(
        gotchas,
        entry_id="0851",
        title="Successor that carries the lesson",
        status="active",
        supersedes=["0841"],
        body="The successor still parses with `_SHA_MARKER` intact.",
    )
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=1)
    loop = _make_loop(tmp_path, pr)

    filed = await loop._file_lesson_coverage_finds(SLUG, tmp_path, set())
    assert filed == 0
    pr.create_issue.assert_not_awaited()
