"""Tests for src/token_drift_filing.py — filing actuator (#11442).

Turns #11441's read-only drift verdict into ONE hydraflow-find issue per
drifting source per ISO week. Dedup uses a REAL DedupStore throughout (a
MagicMock dedup silently no-ops add() and would make every dedup test pass
vacuously — see the implementation plan's explicit warning).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from dedup_store import DedupStore
from token_drift import TokenDriftVerdict
from token_drift_filing import check_token_drift, render_drift_issue, weekly_dedup_key


def _verdict(
    source: str = "implementer",
    *,
    before_share: float = 0.5,
    after_share: float = 0.9,
    sigma: float = 12.0,
    verdict: str = "drift",
) -> TokenDriftVerdict:
    return TokenDriftVerdict(
        source=source,
        before_share=before_share,
        after_share=after_share,
        sigma=sigma,
        verdict=verdict,
    )


def _dedup(tmp_path: Path) -> DedupStore:
    return DedupStore("token_drift_filed", tmp_path / "dedup" / "token_drift.json")


def _config(**overrides: object) -> MagicMock:
    cfg = MagicMock()
    cfg.find_label = ["hydraflow-find"]
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class TestWeeklyDedupKey:
    def test_key_shape(self) -> None:
        when = datetime(2026, 4, 22, tzinfo=UTC)
        assert (
            weekly_dedup_key("implementer", when) == "token_drift:implementer:2026-W17"
        )

    def test_different_source_different_key(self) -> None:
        when = datetime(2026, 4, 22, tzinfo=UTC)
        assert weekly_dedup_key("implementer", when) != weekly_dedup_key(
            "planner", when
        )

    def test_uses_iso_year_not_calendar_year_across_year_boundary(self) -> None:
        """Dec 31 2026 and Jan 1 2027 both fall in ISO week 53 of ISO year
        2026 (isocalendar()), even though Jan 1 2027's calendar .year is
        2027 — the key must key off isocalendar(), not .year."""
        dec_31 = datetime(2026, 12, 31, tzinfo=UTC)
        jan_1 = datetime(2027, 1, 1, tzinfo=UTC)

        key_dec = weekly_dedup_key("implementer", dec_31)
        key_jan = weekly_dedup_key("implementer", jan_1)

        assert key_dec == key_jan == "token_drift:implementer:2026-W53"

    def test_following_iso_week_produces_a_different_key(self) -> None:
        week17 = datetime(2026, 4, 22, tzinfo=UTC)
        week18 = datetime(2026, 4, 29, tzinfo=UTC)

        assert weekly_dedup_key("implementer", week17) != weekly_dedup_key(
            "implementer", week18
        )


class TestRenderDriftIssue:
    def test_cites_before_after_share_and_sigma(self) -> None:
        title, body = render_drift_issue(
            _verdict(), dedup_key="token_drift:implementer:2026-W17"
        )

        assert "implementer" in title
        assert "50.0%" in title
        assert "90.0%" in title
        assert "50.0%" in body
        assert "90.0%" in body
        assert "12.00" in body
        assert "token_drift:implementer:2026-W17" in body


class TestCheckTokenDrift:
    async def test_drifting_source_files_one_labelled_issue(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=101)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)
        now = datetime(2026, 4, 22, tzinfo=UTC)

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=now,
        )

        assert filed == 1
        pr.create_issue.assert_awaited_once()
        args, kwargs = pr.create_issue.call_args
        labels = args[2] if len(args) > 2 else kwargs.get("labels", [])
        assert "hydraflow-find" in labels
        assert "token-drift" in labels
        assert weekly_dedup_key("implementer", now) in dedup.get()
        bus.publish.assert_awaited_once()

    async def test_non_drift_verdict_files_nothing(self, tmp_path: Path) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict(verdict="stable")],
            now=datetime(2026, 4, 22, tzinfo=UTC),
        )

        assert filed == 0
        pr.create_issue.assert_not_awaited()

    async def test_same_source_same_week_second_tick_dedupes(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=101)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)
        now = datetime(2026, 4, 22, tzinfo=UTC)

        first = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=now,
        )
        second = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=now,
        )

        assert first == 1
        assert second == 0
        pr.create_issue.assert_awaited_once()

    async def test_different_source_same_week_files_separately(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=101)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)
        now = datetime(2026, 4, 22, tzinfo=UTC)

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict("implementer"), _verdict("planner")],
            now=now,
        )

        assert filed == 2
        assert pr.create_issue.await_count == 2

    async def test_same_source_following_iso_week_files_again(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=101)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)

        first = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=datetime(2026, 4, 22, tzinfo=UTC),
        )
        second = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=datetime(2026, 4, 29, tzinfo=UTC),
        )

        assert first == 1
        assert second == 1
        assert pr.create_issue.await_count == 2

    async def test_create_issue_failure_leaves_dedup_unset_for_retry(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(side_effect=RuntimeError("gh boom"))
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)
        now = datetime(2026, 4, 22, tzinfo=UTC)

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=now,
        )

        assert filed == 0
        assert weekly_dedup_key("implementer", now) not in dedup.get()
        bus.publish.assert_not_awaited()

    async def test_create_issue_returns_zero_leaves_dedup_unset(
        self, tmp_path: Path
    ) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=0)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = _dedup(tmp_path)
        now = datetime(2026, 4, 22, tzinfo=UTC)

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=now,
        )

        assert filed == 0
        assert weekly_dedup_key("implementer", now) not in dedup.get()

    async def test_dedup_get_raising_is_swallowed_and_tick_survives(self) -> None:
        config = _config()
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=101)
        bus = MagicMock()
        bus.publish = AsyncMock()
        dedup = MagicMock()
        dedup.get.side_effect = RuntimeError("disk boom")

        filed = await check_token_drift(
            config,
            pr_manager=pr,
            dedup=dedup,
            event_bus=bus,
            verdicts=[_verdict()],
            now=datetime(2026, 4, 22, tzinfo=UTC),
        )

        assert filed == 0
        pr.create_issue.assert_not_awaited()
