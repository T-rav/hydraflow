"""Regression for issue #9241 — loops must not file/commit phantom ``issue #0``.

``PRManager.create_issue`` returns ``0`` on failure — a documented sentinel
("Callers MUST check for 0 before storing or referencing the returned value").
``MemoryBacklogLoop`` previously recorded ``issue=0`` into mirror frontmatter,
git-committed a ``chore(memory-backlog): file issue #0`` entry, AND added the
dedup key (suppressing all future re-filing) whenever ``create_issue`` returned
the sentinel. The live instance committed ``file issues #0, #0, #0...`` to git.

The contract guarded here:

1. ``create_issue`` returns 0 → NO git commit, NO frontmatter record, NO dedup
   add — the entry stays ``pending`` so it re-files next cycle.
2. ``create_issue`` returns a real number → frontmatter records it and a git
   commit lands (positive control — proves the guard didn't break the happy
   path).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from memory_backlog_loop import MemoryBacklogLoop
from memory_backlog_mirror import load_mirror_entry


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _write_mirror_entry(dir_: Path, slug: str) -> Path:
    front = {
        "source": f"feedback_{slug.replace('-', '_')}.md",
        "name": f"Test rule {slug}",
        "description": f"desc for {slug}",
        "status": "pending",
        "issue": None,
        "promoted_in": None,
        "wontfix_reason": None,
        "created": "2026-06-04",
    }
    p = dir_ / f"{slug}.md"
    p.write_text(
        f"---\n{yaml.safe_dump(front, sort_keys=False).rstrip()}\n---\n\n"
        f"Rule: do the thing.\n\n**Why:** because.\n"
    )
    return p


def _git_repo(repo_root: Path, mirror_dir: Path, slug: str) -> tuple[Path, str]:
    """Init a real git repo with one committed mirror entry. Return (path, sha)."""
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    entry_path = _write_mirror_entry(mirror_dir, slug)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo_root,
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return entry_path, base_sha


@pytest.fixture
def env(tmp_path: Path):
    repo_root = tmp_path
    mirror_dir = repo_root / "docs" / "wiki" / "memory-feedback"
    mirror_dir.mkdir(parents=True)
    cfg = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        git_user_email="t@e.st",
        git_user_name="t",
    )
    state = MagicMock()
    state.get_memory_backlog_attempts.return_value = 0
    state.inc_memory_backlog_attempts.return_value = 1
    pr = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup, mirror_dir


def _make_loop(env) -> MemoryBacklogLoop:
    cfg, state, pr, dedup, _ = env
    loop = MemoryBacklogLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=_deps(asyncio.Event()),
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    return loop


@pytest.mark.asyncio
async def test_zero_sentinel_does_not_commit_record_or_dedup(env) -> None:
    """create_issue returns 0 → no commit, no frontmatter record, no dedup add."""
    cfg, _state, pr, dedup, mirror_dir = env
    entry_path, base_sha = _git_repo(cfg.repo_root, mirror_dir, "fb-sentinel")
    pr.create_issue = AsyncMock(return_value=0)
    loop = _make_loop(env)

    result = await loop._do_work()

    # Nothing was filed — the sentinel was caught.
    assert result == {
        "status": "ok",
        "filed": 0,
        "skipped": 0,
        "escalated": 0,
    }
    pr.create_issue.assert_awaited_once()

    # Frontmatter is untouched: still pending, no phantom issue=0.
    after = load_mirror_entry(entry_path)
    assert after.status == "pending"
    assert after.issue is None

    # No git commit was made for a phantom #0.
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_sha == base_sha, "loop committed a phantom issue #0"

    # Dedup key was NOT added — the entry re-files next cycle.
    dedup.set_all.assert_not_called()


@pytest.mark.asyncio
async def test_real_number_commits_and_records(env) -> None:
    """Positive control: a real issue number records frontmatter and commits."""
    cfg, _state, pr, dedup, mirror_dir = env
    entry_path, base_sha = _git_repo(cfg.repo_root, mirror_dir, "fb-real")
    pr.create_issue = AsyncMock(return_value=4321)
    loop = _make_loop(env)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 1,
        "skipped": 0,
        "escalated": 0,
    }
    after = load_mirror_entry(entry_path)
    assert after.status == "issue-open"
    assert after.issue == 4321

    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_sha != base_sha, "loop did not commit the real issue"

    title = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=cfg.repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "#4321" in title
    assert "#0" not in title

    dedup.set_all.assert_called()


@pytest.mark.asyncio
async def test_escalation_zero_sentinel_does_not_dedup(env) -> None:
    """At escalation (>= max attempts), a 0 sentinel skips counting + dedup."""
    cfg, state, pr, dedup, mirror_dir = env
    _write_mirror_entry(mirror_dir, "fb-escalate")
    state.inc_memory_backlog_attempts.return_value = 3  # >= _MAX_ATTEMPTS
    pr.create_issue = AsyncMock(return_value=0)
    loop = _make_loop(env)
    loop._commit_mirror_updates = AsyncMock(return_value=None)

    result = await loop._do_work()

    assert result == {
        "status": "ok",
        "filed": 0,
        "skipped": 0,
        "escalated": 0,
    }
    pr.create_issue.assert_awaited_once()
    # No dedup add — escalation retries next cycle once gh recovers.
    dedup.set_all.assert_not_called()
