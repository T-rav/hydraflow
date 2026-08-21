"""Regression pin (#11442): a ``0`` from ``create_issue`` must not retire a finding.

``PRManager.create_issue`` returns ``0`` on failure without raising. Before the
fix, ``ErosionMetricsLoop._file_findings`` recorded the fingerprint regardless
of the return value, so a failed filing was silently never retried — the same
trap #11522's review closed for class issues in ``_reconcile_class_issues``.
The token-drift actuator's recovery rule rides this path: the
``token_drift:<source>:<window_key>`` entry is written ONLY after a non-zero
issue number, so a failed filing retries on the next tick and a success never
re-files that source+week.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from erosion.token_drift_filing import token_drift_fingerprint
from erosion_metrics_loop import _current_head_sha
from tests.test_erosion_metrics_loop import (
    _commit_all,
    _init_repo,
    _make_dedup,
    _make_loop,
    _make_state,
)
from tests.test_erosion_metrics_loop_token_drift import seed_token_drift


def _prs(*numbers: int) -> MagicMock:
    prs = MagicMock()
    prs.create_issue = AsyncMock(side_effect=list(numbers))
    return prs


def _commit_change(repo: Path, name: str) -> None:
    (repo / "src" / name).write_text("x = 1\n")
    _commit_all(repo, f"add {name}")


async def test_zero_sentinel_leaves_fingerprint_unrecorded_on_the_regular_path(
    tmp_path: Path,
) -> None:
    """Direct pin on ``_file_findings``: a spread finding whose filing returns 0."""
    repo = _init_repo(tmp_path)
    dedup = _make_dedup()
    loop = _make_loop(tmp_path, repo, pr_manager=_prs(0), dedup=dedup)
    candidates = [
        {
            "kind": "spread",
            "fingerprint": "spread:a..b",
            "commit_range": "a..b",
            "finding": MagicMock(
                spread_ratio=2.0, files_touched=1, modules_crossed=2, modules=("x",)
            ),
            "baseline": MagicMock(max_spread_ratio=1.0),
        }
    ]

    filed, capped = await loop._file_findings(candidates)

    assert (filed, capped) == (0, False)
    assert "spread:a..b" not in dedup._store


async def test_failed_token_drift_filing_retries_next_tick(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _current_head_sha(repo)
    _commit_change(repo, "a.py")
    prs = _prs(0, 9001)
    dedup = _make_dedup()
    loop = _make_loop(
        tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
    )
    window_key = seed_token_drift(loop._config, now=datetime.now(UTC))
    fingerprint = token_drift_fingerprint("implementer", window_key)

    first = await loop._do_work()
    assert first is not None and first["filed"] == 0
    assert fingerprint not in dedup._store

    _commit_change(repo, "b.py")
    second = await loop._do_work()

    assert second is not None and second["filed"] == 1
    assert fingerprint in dedup._store
    assert prs.create_issue.await_count == 2


async def test_successful_token_drift_filing_never_refiles_that_week(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    base = _current_head_sha(repo)
    _commit_change(repo, "a.py")
    prs = _prs(9001, 9002)
    dedup = _make_dedup()
    loop = _make_loop(
        tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
    )
    window_key = seed_token_drift(loop._config, now=datetime.now(UTC))

    first = await loop._do_work()
    _commit_change(repo, "b.py")
    second = await loop._do_work()

    assert first is not None and first["filed"] == 1
    assert second is not None and second["filed"] == 0
    assert dedup._store == {token_drift_fingerprint("implementer", window_key)}
    assert prs.create_issue.await_count == 1
