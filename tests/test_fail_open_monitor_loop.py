"""Unit tests for FailOpenMonitorLoop (#10371).

Covers: quiet when no breach / insufficient history, filing a hydraflow-find on
a control-limit breach, per-day dedup, the kill-switch, and
reraise_on_credit_or_bug in the filing except.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import judge_independence as ji
from fail_open_monitor_loop import FailOpenMonitorLoop, breach_fingerprint
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


def _make_dedup(seen: set[str] | None = None) -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set(seen or set())
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    dedup._store = store
    return dedup


def _make_loop(
    tmp_path: Path,
    *,
    dedup: MagicMock | None = None,
    pr_manager: Any = None,
    **config_overrides: Any,
) -> tuple[FailOpenMonitorLoop, Any]:
    bg = make_bg_loop_deps(tmp_path, **config_overrides)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "fail_open_monitor_loop_enabled", True)
    prs = pr_manager if pr_manager is not None else MagicMock()
    if not isinstance(prs.create_issue, AsyncMock):
        prs.create_issue = AsyncMock(return_value=1)
    loop = FailOpenMonitorLoop(
        config=bg.config,
        pr_manager=prs,
        dedup=dedup if dedup is not None else _make_dedup(),
        deps=bg.loop_deps,
    )
    return loop, bg.config


def _seed_spike(config: Any) -> Path:
    """Seed the ledger with 3 quiet days + a 10-event spike day (a breach)."""
    path = ji.ledger_path_for(config)
    for i, d in enumerate(["2026-07-01", "2026-07-02", "2026-07-03"]):
        ji.record_fail_open(
            path,
            lens=None,
            pr=i,
            surface="pr_review",
            classes=frozenset(),
            disposition=ji.FailOpenDisposition.FAIL_OPEN_LEDGERED,
            reason="x",
            ts=f"{d}T00:00:00+00:00",
        )
    for i in range(10):
        ji.record_fail_open(
            path,
            lens=None,
            pr=100 + i,
            surface="pr_review",
            classes=frozenset(),
            disposition=ji.FailOpenDisposition.FAIL_OPEN_LEDGERED,
            reason="x",
            ts="2026-07-04T00:00:00+00:00",
        )
    return path


def test_no_ledger_is_quiet(tmp_path: Path):
    loop, _config = _make_loop(tmp_path)
    result = asyncio.run(loop._do_work())
    assert result["status"] == "ok"
    assert result["breached"] is False


def test_breach_files_one_hydraflow_find(tmp_path: Path):
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=1)
    loop, config = _make_loop(tmp_path, pr_manager=prs)
    _seed_spike(config)
    result = asyncio.run(loop._do_work())
    assert result["breached"] is True
    assert result["day"] == "2026-07-04"
    assert result["filed"] == 1
    prs.create_issue.assert_awaited_once()
    _title, body = prs.create_issue.await_args.args
    assert "control limit" in body.lower()


def test_breach_is_deduped_per_day(tmp_path: Path):
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=1)
    dedup = _make_dedup({breach_fingerprint("2026-07-04")})
    loop, config = _make_loop(tmp_path, pr_manager=prs, dedup=dedup)
    _seed_spike(config)
    result = asyncio.run(loop._do_work())
    assert result["breached"] is True
    assert result["filed"] == 0
    prs.create_issue.assert_not_awaited()


def test_kill_switch_config_disabled(tmp_path: Path):
    loop, config = _make_loop(tmp_path)
    object.__setattr__(config, "fail_open_monitor_loop_enabled", False)
    _seed_spike(config)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "config_disabled"}


def test_credit_exhaustion_reraised_from_filing(tmp_path: Path):
    prs = MagicMock()
    prs.create_issue = AsyncMock(side_effect=CreditExhaustedError("no credit"))
    loop, config = _make_loop(tmp_path, pr_manager=prs)
    _seed_spike(config)
    with __import__("pytest").raises(CreditExhaustedError):
        asyncio.run(loop._do_work())
