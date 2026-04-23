"""Unit tests for src/corpus_learning_loop.py (§4.1 Phase 2 skeleton).

Covers:

- construction (worker_name wired, deps stored)
- ``_get_default_interval`` reads ``config.corpus_learning_interval``
- ``_do_work`` short-circuits with ``{"status": "disabled"}`` when the
  ``enabled_cb`` kill-switch returns ``False``
- Task 11 escape-signal reader: ``_list_escape_signals`` parses
  ``PRManager.list_issues_by_label`` output into :class:`EscapeSignal`
  dataclasses, filters to the configured lookback window, short-circuits
  cleanly on empty input, and is invoked by ``_do_work`` when enabled.

Tasks 12+ (synthesis, validation, PR filing) are out of scope and not
exercised here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from corpus_learning_loop import (
    DEFAULT_ESCAPE_LABEL,
    DEFAULT_LOOKBACK_DAYS,
    CorpusLearningLoop,
    EscapeSignal,
)
from events import EventBus


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: object | None = None,
    **config_overrides: object,
) -> CorpusLearningLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        **config_overrides,
    )
    pr_manager = prs if prs is not None else AsyncMock()
    dedup = MagicMock()
    return CorpusLearningLoop(
        config=cfg,
        prs=pr_manager,
        dedup=dedup,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_loop_constructs_with_expected_worker_name(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._worker_name == "corpus_learning"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    # Default from the ``corpus_learning_interval`` Field (weekly cadence).
    loop = _loop(tmp_path)
    assert loop._get_default_interval() == 604800


def test_default_interval_reflects_config_override(tmp_path: Path) -> None:
    loop = _loop(tmp_path, corpus_learning_interval=7200)
    assert loop._get_default_interval() == 7200


def test_do_work_short_circuits_when_kill_switch_disabled(tmp_path: Path) -> None:
    loop = _loop(tmp_path, enabled=False)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "disabled"}


def test_do_work_returns_dict_when_enabled(tmp_path: Path) -> None:
    # When enabled, the skeleton still returns a dict — Tasks 12+ will
    # expand it with synthesis stats. The only contract here is that
    # it's a non-``disabled`` dict so the base-class status reporter can
    # publish it.
    loop = _loop(tmp_path)
    result = asyncio.run(loop._do_work())
    assert isinstance(result, dict)
    assert result.get("status") != "disabled"


# ---------------------------------------------------------------------------
# Task 11 — escape-signal reader
# ---------------------------------------------------------------------------


def _iso_now_offset(days: int) -> str:
    """Return an ISO-8601 UTC timestamp ``days`` ago (negative => past)."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_list_escape_signals_parses_issues_into_dataclass(tmp_path: Path) -> None:
    recent = _iso_now_offset(-2)
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 101,
                "title": "diff-sanity missed dead config",
                "body": "plan vs diff drift",
                "updated_at": recent,
            },
            {
                "number": 102,
                "title": "scope-check let duplicate slip",
                "body": "no dup guard",
                "updated_at": recent,
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    prs.list_issues_by_label.assert_awaited_once_with(DEFAULT_ESCAPE_LABEL)
    assert len(signals) == 2
    assert all(isinstance(sig, EscapeSignal) for sig in signals)
    assert [sig.issue_number for sig in signals] == [101, 102]
    assert signals[0].title == "diff-sanity missed dead config"
    assert signals[0].body == "plan vs diff drift"
    assert signals[0].updated_at == recent
    assert signals[0].label == DEFAULT_ESCAPE_LABEL


def test_list_escape_signals_filters_out_stale_issues(tmp_path: Path) -> None:
    # With a 30-day lookback, a 45-day-old issue must be dropped but a
    # 5-day-old one retained.
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 200,
                "title": "fresh",
                "body": "",
                "updated_at": _iso_now_offset(-5),
            },
            {
                "number": 201,
                "title": "stale",
                "body": "",
                "updated_at": _iso_now_offset(-45),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals(lookback_days=30))

    assert [sig.issue_number for sig in signals] == [200]


def test_list_escape_signals_short_circuits_on_empty_list(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert signals == []
    prs.list_issues_by_label.assert_awaited_once()


def test_list_escape_signals_uses_custom_label(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs)

    asyncio.run(loop._list_escape_signals(label="skill-regression"))

    prs.list_issues_by_label.assert_awaited_once_with("skill-regression")


def test_list_escape_signals_skips_rows_without_number(tmp_path: Path) -> None:
    # Defensive parsing: gh's JSON contract is stable but any dict missing
    # ``number`` is useless for downstream synthesis and must be dropped
    # rather than propagated as an :class:`EscapeSignal(issue_number=0)`.
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 0,
                "title": "zero",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
            {"title": "missing-number", "body": "", "updated_at": _iso_now_offset(-1)},
            {
                "number": 42,
                "title": "real",
                "body": "body",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert [sig.issue_number for sig in signals] == [42]


def test_list_escape_signals_drops_rows_with_unparseable_updated_at(
    tmp_path: Path,
) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {"number": 1, "title": "bad ts", "body": "", "updated_at": "not-a-date"},
            {
                "number": 2,
                "title": "good ts",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert [sig.issue_number for sig in signals] == [2]


def test_do_work_invokes_escape_signal_reader_when_enabled(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 7,
                "title": "escape",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    prs.list_issues_by_label.assert_awaited_once_with(DEFAULT_ESCAPE_LABEL)
    assert isinstance(result, dict)
    assert result.get("escape_issues_seen") == 1
    # Synthesis stats are still zero — that work lands in Task 12.
    assert result.get("cases_proposed") == 0
    assert result.get("escalated") == 0


def test_do_work_does_not_query_when_disabled(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs, enabled=False)

    result = asyncio.run(loop._do_work())

    assert result == {"status": "disabled"}
    prs.list_issues_by_label.assert_not_awaited()


def test_default_lookback_days_is_reasonable() -> None:
    # The reader's default must clearly prefer recency — anything over
    # ~90d stops being "recent escape signals" and starts being archival
    # noise. Task 15 will surface this as a tunable config field.
    assert 7 <= DEFAULT_LOOKBACK_DAYS <= 90
