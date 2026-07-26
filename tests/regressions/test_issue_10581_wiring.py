"""Regression for issue #10581 — wiring the prose-drift channel into RepoWikiLoop.

PR #10638 added a REPORT-ONLY ``wiki_drift_detector.detect_prose_drift`` (with
its own ``ProseDriftFinding`` type) but left it unwired, so prose-form citations
to unimplemented code never surfaced in production. This wires it into
``RepoWikiLoop``'s drift pass as ``_detect_prose_drift`` (phase 9c): the loop
calls ``detect_prose_drift``, logs each suspect entry, and reports the suspect
count so the heal surfaces it via ``stats["prose_drift_suspects"]``.

The channel is deliberately REPORT-ONLY — the #10638 safety boundary. A
heuristic prose verdict must cost a log line, not a ``status: stale`` flip, so
the wiring must never mutate entry status (it must never call
``apply_drift_markers`` on prose findings).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import repo_wiki_loop
from base_background_loop import LoopDeps
from repo_wiki import RepoWikiStore
from repo_wiki_loop import RepoWikiLoop
from wiki_drift_detector import detect_prose_drift

REPO_SLUG = "o/r"


def _make_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=MagicMock(),
        interval_cb=None,
    )


def _make_config(wiki_root: Path) -> MagicMock:
    config = MagicMock()
    config.repo_wiki_interval = 3600
    config.dry_run = False
    config.repo_wiki_git_backed = True
    config.semantic_drift_enabled = False
    config.semantic_drift_min_age_days = 30
    config.semantic_drift_max_entries_per_tick = 10
    config.data_path.return_value = wiki_root / "wiki_maint_queue.json"
    return config


def _make_loop(wiki_root: Path) -> RepoWikiLoop:
    store = RepoWikiStore(wiki_root)
    return RepoWikiLoop(
        config=_make_config(wiki_root), wiki_store=store, deps=_make_deps()
    )


def _build_src(repo_root: Path) -> None:
    """A small ``src/`` tree: ``escape/detect.py`` exists but does NOT define
    ``DETECTOR_GENERATION`` (that mismatch is the unimplemented-proposal drift),
    while ``runner.py`` genuinely defines ``handle_start``."""
    escape = repo_root / "src" / "escape"
    escape.mkdir(parents=True)
    (escape / "__init__.py").write_text("", encoding="utf-8")
    (escape / "detect.py").write_text(
        "class Detector:\n    def run(self):\n        return None\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "runner.py").write_text(
        "def handle_start():\n    return True\n",
        encoding="utf-8",
    )


def _write_entry(
    tracked_root: Path,
    topic: str,
    *,
    body: str,
    entry_id: str,
    status: str = "active",
) -> Path:
    topic_dir = tracked_root / REPO_SLUG / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"0204-{entry_id}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        "source_issue: 10581\n"
        "source_phase: plan\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def _drifted_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A tracked layout with one prose-drift entry + one clean entry.

    Returns ``(tracked_root, repo_root, drifted_entry_path)``.
    """
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    drifted = _write_entry(
        tracked_root,
        "architecture",
        body="We will add a `DETECTOR_GENERATION` constant in `escape/detect.py`.",
        entry_id="01JF00000000000000000001",
    )
    _write_entry(
        tracked_root,
        "gotchas",
        body="The `handle_start` entrypoint lives in `runner.py`.",
        entry_id="01JF00000000000000000002",
    )
    return tracked_root, repo_root, drifted


@pytest.mark.asyncio
async def test_drift_pass_invokes_detector_and_surfaces_suspect_count(
    tmp_path: Path,
) -> None:
    # Arrange
    loop = _make_loop(tmp_path / "wiki")
    tracked_root, repo_root, _ = _drifted_layout(tmp_path)

    # The count the wiring must surface == the total suspect symbols the
    # report-only detector finds for these entries (derived, not hard-coded).
    reference = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug=REPO_SLUG
    )
    expected = sum(len(f.suspect_symbols) for f in reference)
    assert expected >= 1  # scenario is non-trivial

    calls: list[dict] = []
    real = repo_wiki_loop.detect_prose_drift

    def _spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    # Act
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(repo_wiki_loop, "detect_prose_drift", _spy)
        count = await loop._detect_prose_drift(
            [REPO_SLUG], tracked_root, repo_root=repo_root
        )

    # Assert: the drift pass invoked the detector and surfaced its suspect count.
    assert calls, "drift pass did not invoke detect_prose_drift"
    assert count == expected


@pytest.mark.asyncio
async def test_drift_pass_is_report_only_no_status_mutation(
    tmp_path: Path,
) -> None:
    # Arrange
    loop = _make_loop(tmp_path / "wiki")
    tracked_root, repo_root, drifted = _drifted_layout(tmp_path)
    before = drifted.read_text(encoding="utf-8")

    # Act
    count = await loop._detect_prose_drift(
        [REPO_SLUG], tracked_root, repo_root=repo_root
    )

    # Assert: a suspect was found, but the entry file is byte-for-byte unchanged
    # — no ``status: stale`` flip, no ``stale_reason`` annotation.
    assert count >= 1
    after = drifted.read_text(encoding="utf-8")
    assert after == before
    assert "status: active" in after
    assert "stale_reason" not in after


@pytest.mark.asyncio
async def test_drift_pass_logs_each_suspect_entry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    loop = _make_loop(tmp_path / "wiki")
    tracked_root, repo_root, _ = _drifted_layout(tmp_path)

    # Act
    with caplog.at_level(logging.INFO, logger="hydraflow.repo_wiki_loop"):
        await loop._detect_prose_drift(
            [REPO_SLUG], tracked_root, repo_root=repo_root
        )

    # Assert: a phase-9c-style report line names the drift channel + the entry.
    prose_logs = [r for r in caplog.records if "prose drift" in r.getMessage().lower()]
    assert prose_logs, "no prose-drift report line was logged"
    assert any("01JF00000000000000000001" in r.getMessage() for r in prose_logs)


@pytest.mark.asyncio
async def test_drift_pass_clean_layout_reports_zero(tmp_path: Path) -> None:
    # Arrange: only the clean entry (a genuine, resolvable citation).
    loop = _make_loop(tmp_path / "wiki")
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "gotchas",
        body="The `handle_start` entrypoint lives in `runner.py`.",
        entry_id="01JF00000000000000000009",
    )

    # Act
    count = await loop._detect_prose_drift(
        [REPO_SLUG], tracked_root, repo_root=repo_root
    )

    # Assert
    assert count == 0


@pytest.mark.asyncio
async def test_drift_pass_no_tracked_root_is_noop(tmp_path: Path) -> None:
    # Arrange: non-git-backed heals pass ``tracked_root=None``.
    loop = _make_loop(tmp_path / "wiki")

    # Act
    count = await loop._detect_prose_drift(
        [REPO_SLUG], None, repo_root=tmp_path / "repo"
    )

    # Assert
    assert count == 0
