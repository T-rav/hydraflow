"""Regression for issue #10767.

``WikiRotDetectorLoop._tick_repo`` filed one ``hydraflow-find`` issue per
broken cite with no upper bound per tick. A wiki compile that promotes many
entries at once — or any widening of cite extraction (#10762 Style-D) — could
open dozens of issues in a single weekly tick, flooding the board.

The fix adds ``wiki_rot_detector_max_issues_per_tick``: a shared per-tick
filing budget across all repos and cite styles. Once the cap is hit, the
remaining broken cites are reported as ONE summary issue instead of one each.
The budget gates filing ONLY — ``broken_subjects`` (which drives
``reconcile_open``) is never capped, so a rate-limited cite cannot look
"resolved" and auto-close a live escalation (patterns/0576).

This file also pins the Style-D bare-cite wiring end-to-end (#10762): an
imperative bare tool cite that resolves nowhere in ``src`` files a finding,
while one that resolves to a real module does not.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from wiki_rot_detector_loop import WikiRotDetectorLoop


def _loop(tmp_path: Path, *, cap: int, dedup_seen: set[str] | None = None):
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        wiki_rot_detector_max_issues_per_tick=cap,
    )
    cfg.repo_root = tmp_path  # type: ignore[misc]
    state = MagicMock()
    state.get_wiki_rot_attempts.return_value = 0
    state.inc_wiki_rot_attempts.return_value = 1
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = MagicMock()
    dedup.get.return_value = dedup_seen if dedup_seen is not None else set()
    wiki_store = MagicMock()
    slug = "hydra/hydraflow"
    wiki_dir = tmp_path / "wiki" / slug
    wiki_dir.mkdir(parents=True, exist_ok=True)
    wiki_store.repo_dir.return_value = wiki_dir
    wiki_store.list_repos.return_value = [slug]
    (tmp_path / "src").mkdir(exist_ok=True)
    loop = WikiRotDetectorLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        wiki_store=wiki_store,
        deps=LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: True,
        ),
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    return loop, pr, wiki_dir


async def test_per_tick_cap_summarizes_overflow(tmp_path: Path) -> None:
    loop, pr, wiki_dir = _loop(tmp_path, cap=2)
    # Five distinct broken Style-A cites (missing modules) in one tick.
    (wiki_dir / "patterns.md").write_text(
        "# Patterns\n\n## E\n\n"
        "src/gone_a.py:x1 src/gone_b.py:x2 src/gone_c.py:x3 "
        "src/gone_d.py:x4 src/gone_e.py:x5\n"
    )

    stats = await loop._do_work()

    # 2 individual finds + 1 summary = 3 create_issue calls.
    assert pr.create_issue.await_count == 3
    assert stats["issues_filed"] == 3
    # The last call is the summary.
    title, body, labels = pr.create_issue.await_args_list[-1].args
    assert "over per-tick filing cap" in title
    assert "3 broken cite" in body  # 5 broken - 2 filed = 3 overflow
    assert set(labels) == {"hydraflow-find", "wiki-rot"}


async def test_cap_does_not_gate_broken_subjects(tmp_path: Path) -> None:
    # broken_subjects must include EVERY broken cite (even capped ones) so a
    # live escalation for a rate-limited cite is not auto-closed.
    loop, pr, wiki_dir = _loop(tmp_path, cap=1)
    (wiki_dir / "patterns.md").write_text(
        "# P\n\n## E\n\nsrc/gone_a.py:x1 src/gone_b.py:x2 src/gone_c.py:x3\n"
    )
    result = await loop._tick_repo("hydra/hydraflow", "hydra/hydraflow", _budget(cap=1))
    assert len(result["broken_subjects"]) == 3  # all 3, not just the 1 filed
    assert result["filed"] == 1  # only 1 individually filed under the cap


async def test_bare_cite_phantom_tool_files_finding(tmp_path: Path) -> None:
    loop, pr, wiki_dir = _loop(tmp_path, cap=10)
    (wiki_dir / "gotchas.md").write_text(
        "# Gotchas\n\n## E\n\nRun `phantom_lesson_tool` to tier predecessors.\n"
    )
    stats = await loop._do_work()
    assert stats["issues_filed"] == 1
    title, _body, _labels = pr.create_issue.await_args_list[0].args
    assert "phantom_lesson_tool" in title


async def test_bare_cite_resolving_to_real_module_is_not_flagged(
    tmp_path: Path,
) -> None:
    loop, pr, wiki_dir = _loop(tmp_path, cap=10)
    (tmp_path / "src" / "real_helper.py").write_text("def go():\n    return 1\n")
    (wiki_dir / "gotchas.md").write_text(
        "# Gotchas\n\n## E\n\nRun `real_helper` to do the thing.\n"
    )
    stats = await loop._do_work()
    assert stats["issues_filed"] == 0
    pr.create_issue.assert_not_awaited()


def _budget(*, cap: int):
    from wiki_rot_detector_loop import _FilingBudget

    return _FilingBudget(cap=cap)
