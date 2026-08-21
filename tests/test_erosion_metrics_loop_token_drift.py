"""ErosionMetricsLoop — token-drift filing actuator wiring (#11442).

Seeds real ``inferences.jsonl`` telemetry under the loop's own (tmp-scoped)
config, pins a baseline through ``token_drift.pin_baseline``, and drives the
third whole-repo candidate kind ``token_drift`` through the REGULAR
``_file_findings`` path (not the class-issue reconciler): one candidate per
drifting source per ISO week, fingerprinted ``token_drift:<source>:<week>``.

The seeding helpers here are shared with the MockWorld scenario and the
#11442 regression pin, so the band arithmetic lives in one place: the
baseline alternates between two readings so σ̂ is non-zero and the engine
computes a numeric sigma (``sigma`` is never pre-set in the seed).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from erosion.token_drift_filing import (
    TOKEN_DRIFT_KIND,
    render_token_drift,
    token_drift_fingerprint,
)
from erosion_metrics_loop import _ISSUE_LABELS, _current_head_sha, _render_finding
from tests.test_erosion_metrics_loop import (
    _commit_all,
    _init_repo,
    _make_dedup,
    _make_loop,
    _make_state,
)
from token_drift import (
    MIN_BASELINE_WINDOWS,
    TokenBaselineLedger,
    iso_week_windows,
    pin_baseline,
    token_baseline_path,
)

#: Every seeded issue totals this many tokens, so the median-tokens chart
#: stays flat across baseline and trailing weeks and only SHARES can drift.
ISSUE_TOTAL_TOKENS = 100_000

# Two alternating baseline readings (shares .40/.20/.40 and .42/.22/.36):
# σ̂ = MR̄/d₂ = 0.02/1.128 ≈ 0.0177 for implementer and planner, so the
# one-sided L=3 limits sit at ≈ 0.463 and ≈ 0.263 respectively.
_BASELINE_SHAPES: tuple[dict[str, int], dict[str, int]] = (
    {"implementer": 40_000, "planner": 20_000, "reviewer": 40_000},
    {"implementer": 42_000, "planner": 22_000, "reviewer": 36_000},
)
#: Trailing week: implementer climbs to 60% (≈10.7σ), the others fall.
DRIFTED_WEEK: dict[str, int] = {
    "implementer": 60_000,
    "planner": 22_000,
    "reviewer": 18_000,
}
#: A second issue landing late in the same trailing week: with both issues
#: counted, implementer sits at 55% (still drifting, already filed) and
#: planner climbs to 36% (≈8.5σ) — a second source drifting in the same week.
SECOND_DRIFT: dict[str, int] = {"implementer": 50_000, "planner": 50_000}


def iso_week_key(when: datetime) -> str:
    year, week, _weekday = when.isocalendar()
    return f"{year}-W{week:02d}"


def _rows(issue: int, split: dict[str, int], ts: datetime) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": ts.isoformat(),
            "issue_number": issue,
            "source": source,
            "input_tokens": tokens // 2,
            "output_tokens": tokens - tokens // 2,
            "total_tokens": tokens,
        }
        for source, tokens in split.items()
    ]


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def seed_token_drift(config: Any, *, now: datetime) -> str:
    """Seed ``MIN_BASELINE_WINDOWS`` steady weeks, pin the baseline, then one
    trailing complete week where ``implementer``'s share breaches the band.

    Returns the trailing window's ISO-week key (the fingerprint's week part).
    """
    baseline_rows: list[dict[str, Any]] = []
    for k in range(2, 2 + MIN_BASELINE_WINDOWS):
        baseline_rows += _rows(
            100 + k, _BASELINE_SHAPES[k % 2], now - timedelta(days=7 * k)
        )
    windows = iso_week_windows(baseline_rows, now=now, windows=MIN_BASELINE_WINDOWS)
    TokenBaselineLedger(token_baseline_path(config.data_root)).record(
        pin_baseline(windows, pinned_at=now)
    )
    trailing = now - timedelta(days=7)
    _append_rows(
        config.cost_inferences_path, baseline_rows + _rows(201, DRIFTED_WEEK, trailing)
    )
    return iso_week_key(trailing)


def seed_second_drifting_source(config: Any, *, now: datetime) -> None:
    """Append late-arriving rows that push ``planner`` over the band too."""
    _append_rows(
        config.cost_inferences_path,
        _rows(202, SECOND_DRIFT, now - timedelta(days=7)),
    )


def _prs(*numbers: int) -> MagicMock:
    prs = MagicMock()
    prs.create_issue = AsyncMock(side_effect=list(numbers))
    return prs


class TestTokenDriftCandidates:
    def test_drifted_source_yields_one_regular_candidate(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo)
        window_key = seed_token_drift(loop._config, now=datetime.now(UTC))

        candidates = loop._repo_wide_candidates(repo)

        drift = [c for c in candidates if c["kind"] == TOKEN_DRIFT_KIND]
        assert len(drift) == 1
        assert drift[0]["source"] == "implementer"
        assert drift[0]["fingerprint"] == token_drift_fingerprint(
            "implementer", window_key
        )
        assert not drift[0].get("class_issue")

    def test_no_baseline_yields_nothing_and_logs_reason_at_info(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        repo = _init_repo(tmp_path)
        loop = _make_loop(tmp_path, repo)

        with caplog.at_level(logging.INFO, logger="hydraflow.erosion_metrics"):
            candidates = loop._repo_wide_candidates(repo)

        assert candidates == []
        info = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any(
            "no_baseline" in r.getMessage() and "pin_token_baseline" in r.getMessage()
            for r in info
        )


class TestTokenDriftFiling:
    async def test_tick_files_one_issue_with_loop_labels_and_records_fingerprint(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        (repo / "src" / "a.py").write_text("x = 1\n")
        _commit_all(repo, "change")
        prs = _prs(9001)
        dedup = _make_dedup()
        loop = _make_loop(
            tmp_path, repo, state=_make_state(base), pr_manager=prs, dedup=dedup
        )
        window_key = seed_token_drift(loop._config, now=datetime.now(UTC))

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "ok"
        assert result["filed"] == 1
        assert result["candidates"] == 1
        assert result["token_drift"] == {
            "window_key": window_key,
            "drifting": ["implementer"],
        }
        call = prs.create_issue.await_args
        assert call.kwargs["labels"] == _ISSUE_LABELS
        assert call.args[0] == (
            f"Token drift: `implementer` share 41.0% → 60.0% (10.7σ) "
            f"in week {window_key}"
        )
        assert token_drift_fingerprint("implementer", window_key) in dedup._store

    async def test_same_week_second_tick_files_nothing(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        (repo / "src" / "a.py").write_text("x = 1\n")
        _commit_all(repo, "change")
        prs = _prs(9001, 9002)
        loop = _make_loop(tmp_path, repo, state=_make_state(base), pr_manager=prs)
        seed_token_drift(loop._config, now=datetime.now(UTC))
        await loop._do_work()

        (repo / "src" / "b.py").write_text("y = 2\n")
        _commit_all(repo, "another change")
        second = await loop._do_work()

        assert second is not None
        assert second["filed"] == 0
        assert prs.create_issue.await_count == 1

    async def test_no_drift_leaves_result_without_token_drift_key(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base = _current_head_sha(repo)
        (repo / "src" / "a.py").write_text("x = 1\n")
        _commit_all(repo, "change")
        prs = _prs(9001)
        loop = _make_loop(tmp_path, repo, state=_make_state(base), pr_manager=prs)

        result = await loop._do_work()

        assert result is not None
        assert result["filed"] == 0
        assert TOKEN_DRIFT_KIND not in result
        prs.create_issue.assert_not_awaited()


def test_render_finding_dispatches_token_drift_kind() -> None:
    candidate = {
        "kind": TOKEN_DRIFT_KIND,
        "fingerprint": token_drift_fingerprint("planner", "2026-W33"),
        "source": "planner",
        "before_share": 0.21,
        "after_share": 0.36,
        "sigma": 8.46,
        "window_key": "2026-W33",
    }
    assert _render_finding(candidate) == render_token_drift(candidate)
