"""Regression pin: a failed class-issue creation must never poison the dedup store.

``PRManager.create_issue`` returns ``0`` on failure instead of raising. Before
the fix, ``ErosionMetricsLoop._reconcile_class_issues`` recorded
``"mass:class:#0:<digest>"`` and every later tick read issue #0 as
"open, unreadable" — the mass (or suite-hygiene) class issue was silently never
filed again. Both failure shapes (the 0 sentinel and a raised error) must leave
the store free of any entry for that kind so the next tick retries.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from erosion_metrics_loop import _current_head_sha, find_class_issue_entry
from tests.test_erosion_metrics_loop import (
    _commit_all,
    _init_repo,
    _make_dedup,
    _make_loop,
    _make_state,
)

_GOD_CLASS = "class Hub:\n" + "".join(
    f"    def m{i}(self):\n        return 1\n" for i in range(40)
)


def _repo_with_god_class(tmp_path: Path) -> tuple[Path, str]:
    repo = _init_repo(tmp_path)
    base = _current_head_sha(repo)
    (repo / "src" / "hub.py").write_text(_GOD_CLASS)
    _commit_all(repo, "god class")
    return repo, base


def _failing_prs(failure: object) -> MagicMock:
    prs = MagicMock()
    prs.create_issue = (
        AsyncMock(return_value=failure)
        if not isinstance(failure, Exception)
        else AsyncMock(side_effect=failure)
    )
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.update_issue_body = AsyncMock()
    return prs


async def test_zero_sentinel_leaves_no_class_entry_behind(tmp_path: Path) -> None:
    repo, base = _repo_with_god_class(tmp_path)
    dedup = _make_dedup()
    loop = _make_loop(
        tmp_path, repo, state=_make_state(base), pr_manager=_failing_prs(0), dedup=dedup
    )

    result = await loop._do_work()

    assert result["filed"] == 0
    assert find_class_issue_entry(dedup._store, "mass") is None
    assert not any(entry.startswith("mass:class:#0") for entry in dedup._store)


async def test_raised_create_error_leaves_no_class_entry_behind(tmp_path: Path) -> None:
    repo, base = _repo_with_god_class(tmp_path)
    dedup = _make_dedup()
    loop = _make_loop(
        tmp_path,
        repo,
        state=_make_state(base),
        pr_manager=_failing_prs(RuntimeError("gh: 502")),
        dedup=dedup,
    )

    result = await loop._do_work()

    assert result["filed"] == 0
    assert find_class_issue_entry(dedup._store, "mass") is None
