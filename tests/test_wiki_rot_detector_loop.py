"""Tests for WikiRotDetectorLoop (spec §4.9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    wiki_store = MagicMock()
    wiki_store.list_repos.return_value = []
    return cfg, state, pr_manager, dedup, wiki_store


def _loop(env, *, enabled: bool = True) -> WikiRotDetectorLoop:
    cfg, state, pr, dedup, wiki_store = env
    return WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "wiki_rot_detector"
    assert loop._get_default_interval() == 604800


async def test_do_work_noop_when_no_repos(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "noop"
    assert stats["repos_scanned"] == 0
    _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_do_work_disabled_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    # The base class short-circuits ``run``, not ``_do_work``; we test the
    # explicit kill-switch guard at the top of ``_do_work``.
    stats = await loop._do_work()
    assert stats["status"] == "disabled"


async def test_tick_repo_files_issue_on_broken_cite(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Seed a minimal wiki directory with one entry that cites a missing
    # symbol in a module that *does* exist.
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    entry = wiki_dir / "patterns.md"
    entry.write_text(
        "# Patterns\n\n## Entry A\n\n"
        "The guard lives in src/foo.py:bar - see ADR-0099.\n"
    )
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]

    # Seed HydraFlow-self source so AST verification resolves to a real
    # module without the missing symbol.
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "foo.py").write_text("def other():\n    return 1\n")
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 1, stats
    pr.create_issue.assert_awaited_once()
    title, body, labels = pr.create_issue.await_args.args
    assert "Wiki rot" in title
    assert "src/foo.py:bar" in title
    assert "Did you mean: other" in body
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_tick_repo_dedups_repeat_cite(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {f"wiki_rot_detector:{slug}:src/foo.py:bar"}
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["issues_filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_tick_repo_escalates_on_third_attempt(
    tmp_path: Path,
    loop_env,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    # Not already deduped — simulate "new" fire but 3rd attempt counter.
    dedup.get.return_value = set()
    state.get_wiki_rot_attempts.return_value = 2
    state.inc_wiki_rot_attempts.return_value = 3

    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "patterns.md").write_text("src/foo.py:bar\n")
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    cfg.repo_root = tmp_path  # type: ignore[misc]

    loop = _loop((cfg, state, pr, dedup, wiki_store))
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()

    assert stats["escalations"] == 1, stats
    assert stats["issues_filed"] == 1  # filed + escalated in same tick
    # Two create_issue calls: the find and the escalation.
    calls = pr.create_issue.await_args_list
    assert len(calls) == 2
    labels_escalate = calls[-1].args[2]
    assert set(labels_escalate) == {"hitl-escalation", "wiki-rot-stuck"}


async def test_reconcile_clears_dedup_and_attempts(
    tmp_path: Path,
    loop_env,
    monkeypatch,
) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env
    slug = "hydra/hydraflow"
    dedup.get.return_value = {
        f"wiki_rot_detector:{slug}:src/foo.py:bar",
        f"wiki_rot_detector:{slug}:src/foo.py:other",  # unrelated, stays
    }
    closed_payload = [
        {
            "number": 901,
            "title": f"Wiki rot stuck: {slug} cites missing src/foo.py:bar",
            "body": f"Repo: `{slug}`",
        },
    ]

    async def fake_list(*_a, **_kw):
        return closed_payload

    loop = _loop(loop_env)
    monkeypatch.setattr(loop, "_gh_closed_escalations", fake_list)

    await loop._reconcile_closed_escalations()

    state.clear_wiki_rot_attempts.assert_any_call(f"{slug}:src/foo.py:bar")
    # set_all called with the surviving key.
    remaining_calls = [c.args[0] for c in dedup.set_all.call_args_list]
    assert remaining_calls, "dedup.set_all not invoked"
    assert f"wiki_rot_detector:{slug}:src/foo.py:bar" not in remaining_calls[-1]
    assert f"wiki_rot_detector:{slug}:src/foo.py:other" in remaining_calls[-1]


async def test_reconcile_noop_when_no_closed(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup, wiki_store = loop_env

    async def fake_list(*_a, **_kw):
        return []

    loop = _loop(loop_env)
    monkeypatch.setattr(loop, "_gh_closed_escalations", fake_list)

    await loop._reconcile_closed_escalations()

    dedup.set_all.assert_not_called()
    state.clear_wiki_rot_attempts.assert_not_called()
