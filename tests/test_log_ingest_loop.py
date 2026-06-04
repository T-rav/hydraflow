"""Unit tests for the LogIngestLoop background worker.

Covers the load-bearing behaviours from the design:
disabled no-op, cursor-from-now priming, clustering/normalisation,
ERROR-always + WARNING>=threshold importance, benign-allowlist drops,
dedup against hot-cache / DedupStore / open GitHub issues, the per-run rate
cap with drop logging, the create_issue==0 sentinel guard, the
self-reference guard, and cursor advance across runs.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from log_ingest_loop import LogIngestLoop, normalize_signature
from state import StateTracker

# Applied to the async test classes only; the sync TestNormalization class
# carries no mark so pytest-asyncio doesn't warn about non-async functions.
_aio = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line(level: str, msg: str, logger: str = "hydraflow.worker") -> str:
    return json.dumps(
        {"ts": "2026-06-04T10:00:00Z", "level": level, "msg": msg, "logger": logger}
    )


def _write(path: Path, lines: list[str], *, append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        for ln in lines:
            fh.write(ln + "\n")


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    loop_enabled: bool = True,
    warning_min: int = 50,
    max_issues: int = 3,
    benign: str | None = None,
    create_issue_return: int = 4242,
    open_issues: list[dict] | None = None,
) -> tuple[LogIngestLoop, MagicMock, StateTracker, Path]:
    data_root = tmp_path / "data"
    log_file = data_root / "logs" / "hydraflow.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch()

    kwargs: dict = {
        "data_root": data_root,
        "repo_root": tmp_path / "repo",
        "log_ingest_loop_enabled": loop_enabled,
        "log_ingest_warning_min_count": warning_min,
        "log_ingest_max_issues_per_run": max_issues,
        "log_ingest_log_files": "logs/hydraflow.log",
    }
    if benign is not None:
        kwargs["log_ingest_benign_patterns"] = benign
    config = HydraFlowConfig(**kwargs)

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=open_issues or [])
    prs.create_issue = AsyncMock(return_value=create_issue_return)

    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _n: enabled,
        sleep_fn=AsyncMock(),
    )
    dedup = DedupStore("log_ingest_test", data_root / "dedup" / "log_ingest.json")
    state = StateTracker(tmp_path / "state.json")
    loop = LogIngestLoop(config=config, prs=prs, deps=deps, dedup=dedup, state=state)
    return loop, prs, state, log_file


async def _prime(loop: LogIngestLoop) -> dict:
    """Run the first cycle to prime the cursor (files nothing)."""
    return await loop._do_work()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Normalisation / clustering
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_numbers_and_paths_collapse(self) -> None:
        a = normalize_signature(
            "Failed to fetch issue #1234 from /repos/a/b at 2026-06-04T09:23:01Z"
        )
        b = normalize_signature(
            "Failed to fetch issue #5678 from /repos/c/d at 2026-06-04T11:00:00Z"
        )
        assert a == b
        assert "<N>" in a or "#<N>" in a

    def test_numbers_with_units_collapse(self) -> None:
        assert normalize_signature("slow query took 7ms") == normalize_signature(
            "slow query took 9000ms"
        )

    def test_distinct_messages_do_not_collapse(self) -> None:
        assert normalize_signature("disk full on /var") != normalize_signature(
            "connection refused by peer"
        )

    def test_quoted_strings_and_hashes_collapse(self) -> None:
        a = normalize_signature("bad token 'abc' hash deadbeefcafe1234")
        b = normalize_signature("bad token 'xyz' hash 0123456789abcdef")
        assert a == b


# ---------------------------------------------------------------------------
# Disabled paths
# ---------------------------------------------------------------------------


@_aio
class TestDisabled:
    async def test_kill_switch_disabled_is_noop(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, enabled=False)
        _write(log_file, [_line("ERROR", "boom")])
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        prs.create_issue.assert_not_awaited()

    async def test_config_disabled_is_noop(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, loop_enabled=False)
        _write(log_file, [_line("ERROR", "boom")])
        result = await loop._do_work()
        assert result == {"status": "config_disabled"}
        prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cursor-from-now priming
# ---------------------------------------------------------------------------


@_aio
class TestPriming:
    async def test_first_run_primes_without_filing(self, tmp_path: Path) -> None:
        loop, prs, state, log_file = _make_loop(tmp_path)
        # Pre-existing historical errors must NOT be filed on first run.
        _write(log_file, [_line("ERROR", f"historical boom {i}") for i in range(5)])
        result = await loop._do_work()
        assert result == {"status": "primed", "files_primed": 1}
        prs.create_issue.assert_not_awaited()
        # Cursor is set to current EOF.
        assert state.get_log_ingest_cursor(str(log_file)) == log_file.stat().st_size

    async def test_lines_before_priming_never_filed(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, warning_min=1)
        _write(log_file, [_line("ERROR", "old error") for _ in range(3)])
        await _prime(loop)
        # No new lines appended -> nothing to file.
        result = await loop._do_work()
        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Importance filter
# ---------------------------------------------------------------------------


@_aio
class TestImportanceFilter:
    async def test_error_always_filed(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "kaboom happened once")])
        result = await loop._do_work()
        assert result["filed"] == 1
        prs.create_issue.assert_awaited_once()

    async def test_warning_below_threshold_dropped(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, warning_min=50)
        await _prime(loop)
        _write(log_file, [_line("WARNING", f"minor hiccup {i}") for i in range(10)])
        result = await loop._do_work()
        assert result["filed"] == 0
        assert result["dropped"] >= 1
        prs.create_issue.assert_not_awaited()

    async def test_warning_at_threshold_filed(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, warning_min=5)
        await _prime(loop)
        _write(log_file, [_line("WARNING", f"recurring warn {i}") for i in range(5)])
        result = await loop._do_work()
        assert result["filed"] == 1
        prs.create_issue.assert_awaited_once()


# ---------------------------------------------------------------------------
# Benign allowlist
# ---------------------------------------------------------------------------


@_aio
class TestBenignAllowlist:
    async def test_benign_error_dropped(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(
            tmp_path, benign="repository not found"
        )
        await _prime(loop)
        _write(log_file, [_line("ERROR", "Repository not found: foo/bar")])
        result = await loop._do_work()
        assert result["filed"] == 0
        assert result["dropped"] >= 1
        prs.create_issue.assert_not_awaited()

    async def test_benign_matches_logger_name(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, benign="hydraflow.noisy")
        await _prime(loop)
        _write(log_file, [_line("ERROR", "some failure", logger="hydraflow.noisy")])
        result = await loop._do_work()
        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Self-reference guard
# ---------------------------------------------------------------------------


@_aio
class TestSelfReferenceGuard:
    async def test_own_logger_skipped(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        _write(
            log_file,
            [_line("ERROR", "filing issue for cluster", logger="hydraflow.log_ingest")],
        )
        result = await loop._do_work()
        assert result["filed"] == 0
        assert result["clusters"] == 0
        prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


@_aio
class TestDedup:
    async def test_second_run_dedups_same_signature(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "duplicate boom 1")])
        first = await loop._do_work()
        assert first["filed"] == 1
        # Same normalised signature (only the trailing number differs).
        _write(log_file, [_line("ERROR", "duplicate boom 2")])
        second = await loop._do_work()
        assert second["filed"] == 0
        assert second["skipped"] == 1
        prs.create_issue.assert_awaited_once()

    async def test_open_github_issue_marker_dedups(self, tmp_path: Path) -> None:
        # Pre-seed an open GitHub issue carrying the cluster's marker.
        loop, prs, _state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "already filed boom")])
        # Compute the sighash the loop will produce and feed it back via the
        # mocked open-issues list.
        from log_ingest_loop import _Cluster

        sig = normalize_signature("already filed boom")
        sighash = _Cluster(signature=sig, level="ERROR").sighash
        prs.list_issues_by_label.return_value = [
            {
                "number": 7,
                "title": "x",
                "body": f"<!-- [log-ingest:{sighash}] -->",
                "updated_at": "",
            }
        ]
        result = await loop._do_work()
        assert result["filed"] == 0
        assert result["skipped"] == 1
        prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Rate cap + drop logging
# ---------------------------------------------------------------------------


@_aio
class TestRateCap:
    async def test_cap_limits_filing_and_reports_capped(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, max_issues=2)
        await _prime(loop)
        # 5 distinct ERROR signatures -> only 2 may be filed this cycle.
        _write(
            log_file,
            [
                _line("ERROR", f"distinct error type {chr(ord('a') + i)} here")
                for i in range(5)
            ],
        )
        result = await loop._do_work()
        assert result["filed"] == 2
        assert result["capped"] == 3
        assert prs.create_issue.await_count == 2

    async def test_capped_clusters_filed_next_cycle(self, tmp_path: Path) -> None:
        # Cap of 2 with 3 distinct ERROR signatures: 2 filed now, 1 deferred.
        loop, prs, _state, log_file = _make_loop(tmp_path, max_issues=2)
        await _prime(loop)
        _write(
            log_file,
            [
                _line("ERROR", f"distinct error type {chr(ord('a') + i)} here")
                for i in range(3)
            ],
        )
        first = await loop._do_work()
        assert first["filed"] == 2
        assert first["capped"] == 1
        # The deferred (previously-capped) signature recurs next cycle and is
        # now filed — it was never recorded in dedup, so it is still novel.
        _write(log_file, [_line("ERROR", "distinct error type c here")])
        second = await loop._do_work()
        assert second["filed"] == 1
        assert second["capped"] == 0
        assert prs.create_issue.await_count == 3


# ---------------------------------------------------------------------------
# create_issue == 0 sentinel guard
# ---------------------------------------------------------------------------


@_aio
class TestZeroSentinelGuard:
    async def test_zero_return_does_not_record_dedup_key(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, create_issue_return=0)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "transient failure boom")])
        result = await loop._do_work()
        assert result["filed"] == 0
        # Dedup key must NOT have been recorded so the next cycle retries.
        assert loop._filed == set()

    async def test_retries_after_zero_then_succeeds(self, tmp_path: Path) -> None:
        loop, prs, _state, log_file = _make_loop(tmp_path, create_issue_return=0)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "flaky create boom")])
        await loop._do_work()  # returns 0, no dedup key
        # create_issue now succeeds; same signature reappears next cycle.
        prs.create_issue.return_value = 555
        _write(log_file, [_line("ERROR", "flaky create boom again")])
        result = await loop._do_work()
        assert result["filed"] == 1
        assert loop._filed  # now recorded


# ---------------------------------------------------------------------------
# Cursor advance across runs
# ---------------------------------------------------------------------------


@_aio
class TestCursorAdvance:
    async def test_cursor_advances_and_only_new_lines_parsed(
        self, tmp_path: Path
    ) -> None:
        loop, prs, state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        offset_after_prime = state.get_log_ingest_cursor(str(log_file))

        _write(log_file, [_line("ERROR", "first batch boom")])
        await loop._do_work()
        offset_after_first = state.get_log_ingest_cursor(str(log_file))
        assert offset_after_first > offset_after_prime

        # No new lines -> nothing filed, cursor unchanged.
        prs.create_issue.reset_mock()
        result = await loop._do_work()
        assert result["filed"] == 0
        assert result["clusters"] == 0
        assert state.get_log_ingest_cursor(str(log_file)) == offset_after_first
        prs.create_issue.assert_not_awaited()

    async def test_truncation_restarts_from_zero(self, tmp_path: Path) -> None:
        loop, prs, state, log_file = _make_loop(tmp_path)
        await _prime(loop)
        _write(log_file, [_line("ERROR", "before rotation boom")])
        await loop._do_work()
        # Simulate log rotation: truncate the file below the stored cursor.
        _write(log_file, [_line("ERROR", "after rotation boom")], append=False)
        result = await loop._do_work()
        # The new (post-rotation) line must be picked up from offset 0.
        assert result["filed"] == 1
