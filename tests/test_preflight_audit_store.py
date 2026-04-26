"""PreflightAuditStore tests (spec §3.5, §6.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from preflight.audit import PreflightAuditEntry, PreflightAuditStore


def _entry(
    ts: str = "2026-04-25T12:00:00Z",
    issue: int = 1,
    cost: float = 1.0,
    wall: float = 60.0,
    status: str = "resolved",
) -> PreflightAuditEntry:
    return PreflightAuditEntry(
        ts=ts,
        issue=issue,
        sub_label="flaky-test-stuck",
        attempt_n=1,
        prompt_hash="sha256:abc",
        cost_usd=cost,
        wall_clock_s=wall,
        tokens=1000,
        status=status,
        pr_url=None,
        diagnosis="x",
        llm_summary="y",
    )


def test_append_and_query_for_issue(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    store.append(_entry(issue=1))
    store.append(_entry(issue=2))
    store.append(_entry(issue=1, ts="2026-04-25T13:00:00Z"))
    assert len(store.entries_for_issue(1)) == 2
    assert len(store.entries_for_issue(2)) == 1


def test_query_window_filters_by_ts(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    old = datetime.now(UTC) - timedelta(hours=48)
    fresh = datetime.now(UTC) - timedelta(hours=1)
    store.append(_entry(ts=old.isoformat().replace("+00:00", "Z")))
    store.append(_entry(ts=fresh.isoformat().replace("+00:00", "Z")))
    stats = store.query_24h()
    assert stats.attempts == 1


def test_resolution_rate(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    store.append(_entry(ts=now, status="resolved"))
    store.append(_entry(ts=now, status="needs_human"))
    store.append(_entry(ts=now, status="resolved"))
    stats = store.query_24h()
    assert stats.resolution_rate == 2 / 3


def test_top_spend(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    for c in [1.0, 5.0, 0.5, 10.0, 2.0]:
        store.append(_entry(cost=c))
    top = store.top_spend(n=3)
    assert [e.cost_usd for e in top] == [10.0, 5.0, 2.0]


def test_percentiles(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for c in [1.0, 2.0, 3.0, 4.0, 5.0]:
        store.append(_entry(ts=now, cost=c, wall=c * 10))
    stats = store.query_24h()
    assert stats.p50_cost_usd == 3.0
    assert stats.p95_cost_usd == 4.8


def test_empty_window(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    stats = store.query_24h()
    assert stats.attempts == 0
    assert stats.resolution_rate == 0.0


def test_top_spend_with_since_filter(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    fresh = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    store.append(_entry(ts=old, cost=100.0))  # expensive but old
    store.append(_entry(ts=fresh, cost=5.0))  # cheap but fresh
    top = store.top_spend(n=5, since=datetime.now(UTC) - timedelta(hours=24))
    assert len(top) == 1
    assert top[0].cost_usd == 5.0


def test_query_7d(tmp_path: Path) -> None:
    store = PreflightAuditStore(tmp_path)
    six_days = (
        (datetime.now(UTC) - timedelta(days=6)).isoformat().replace("+00:00", "Z")
    )
    eight_days = (
        (datetime.now(UTC) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    )
    store.append(_entry(ts=six_days))  # inside 7d window
    store.append(_entry(ts=eight_days))  # outside 7d window
    stats = store.query_7d()
    assert stats.attempts == 1
