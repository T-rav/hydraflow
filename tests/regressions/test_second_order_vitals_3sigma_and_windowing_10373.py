"""Regression: second-order-vitals 3σ decision + non-overlapping windows (#10373 review).

Two review findings on the capstone (#10373):

1. **The 3σ band was untested.** Every fixture used an all-zero baseline, where
   σ̂ = MR̄/1.128 = 0 collapses ``centre == UCL == 0`` and a "breach" degenerates
   to ``value > 0``. A reviewer showed the whole ``centre + 3·σ̂`` band could be
   deleted — compare to the baseline MEAN instead of the UCL — with every test
   still green. ``test_band_*`` below pin the band with a genuinely NON-flat
   baseline (mean 11, UCL ≈ 16.32): a value ABOVE the mean but INSIDE the band
   must NOT breach, and only a value above the UCL does. They FAIL if the band
   is removed (14 > mean 11 would then read as a breach).

2. **Cadence × window overlap.** The loop ticks far more often than one window
   (default 4h tick vs a 7d window), so appending a trailing-window reading on
   every tick stacked ~97%-overlapping observations: a single lingering event
   read as many "sustained" windows and the moving-range σ̂ was deflated by the
   autocorrelation. ``test_windowing_*`` pin that an observation is recorded only
   once a full ``window_days`` has elapsed, so a single event is counted in
   exactly one disjoint window — it can never masquerade as two sustained ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from second_order_vitals_loop import SecondOrderVitalsLoop
from tests.helpers import make_bg_loop_deps
from vitals.control import breaches_upper, individuals_limits
from vitals.models import SERIES_ESCAPES
from vitals.observe import PrimaryHealth
from vitals.verdict import _series_sustained_breach

# Non-flat baseline: mean (centre) 11.0, MR̄ 2.0 → σ̂ = 2/1.128, UCL ≈ 16.32.
_BASELINE = [10.0, 12.0, 10.0, 12.0, 10.0, 12.0]
_WITHIN_BAND = 14.0  # above the mean (11) but inside the band (< UCL)
_ABOVE_UCL = 30.0  # above the UCL


def test_band_has_real_width_between_mean_and_ucl() -> None:
    centre, ucl = individuals_limits(_BASELINE)
    assert centre == 11.0
    assert ucl > 16.0  # ≈ 16.32 — the band is genuinely wider than the mean
    # The probe value used below sits strictly inside the band.
    assert centre < _WITHIN_BAND < ucl


def test_band_value_within_band_is_not_a_breach() -> None:
    # If the 3σ band were deleted (compare to the mean), 14 > 11 would breach.
    assert breaches_upper(_WITHIN_BAND, _BASELINE, min_windows=3) is False


def test_band_value_above_ucl_is_a_breach() -> None:
    assert breaches_upper(_ABOVE_UCL, _BASELINE, min_windows=3) is True


def test_band_sustained_breach_needs_above_ucl_not_above_mean() -> None:
    # The verdict engine's real predicate. recent = [14, 14] (inside the band)
    # must NOT sustained-breach; recent = [30, 30] (above the UCL) must.
    within = [*_BASELINE, _WITHIN_BAND, _WITHIN_BAND]
    above = [*_BASELINE, _ABOVE_UCL, _ABOVE_UCL]
    assert not _series_sustained_breach(
        within, min_baseline_windows=3, sustained_windows=2
    )
    assert _series_sustained_breach(above, min_baseline_windows=3, sustained_windows=2)


class _FakeState:
    """Minimal state backing the three vitals accessors the loop touches."""

    def __init__(self) -> None:
        self._history: dict[str, list[float]] = {}
        self._last = ""
        self._last_obs_ts = ""

    def get_second_order_vitals_series_history(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._history.items()}

    def set_second_order_vitals_series_history(
        self, history: dict[str, list[float]]
    ) -> None:
        self._history = {k: list(v) for k, v in history.items()}

    def get_second_order_vitals_last_verdict(self) -> str:
        return self._last

    def set_second_order_vitals_last_verdict(self, verdict: str) -> None:
        self._last = verdict

    def get_second_order_vitals_last_observation_ts(self) -> str:
        return self._last_obs_ts

    def set_second_order_vitals_last_observation_ts(self, ts: str) -> None:
        self._last_obs_ts = ts


def _build_loop(tmp_path: Path, state: _FakeState) -> SecondOrderVitalsLoop:
    bg = make_bg_loop_deps(tmp_path)
    c = bg.config
    object.__setattr__(c, "data_root", tmp_path / "data")

    def _green(_now: object, _window_days: int) -> PrimaryHealth:
        return PrimaryHealth(ci_pass_rate=1.0, merge_throughput=100)

    class _FakePR:
        async def create_issue(
            self, title: str, body: str, labels: list[str] | None = None
        ) -> int:
            return 1

    return SecondOrderVitalsLoop(
        config=c,
        pr_manager=_FakePR(),
        state=state,
        deps=bg.loop_deps,
        primary_health_reader=_green,
    )


def test_windowing_tick_within_window_records_no_new_observation(
    tmp_path: Path,
) -> None:
    window_days = 7
    t_event = datetime(2026, 5, 1, tzinfo=UTC)
    diag = tmp_path / "data" / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / "escape_ledger.jsonl").write_text(
        json.dumps({"id": "e0", "detected_at": t_event.isoformat()}) + "\n"
    )
    loop = _build_loop(tmp_path, _FakeState())

    # First observation just after the event → the event is in-window (1.0).
    h1 = loop._append_observations(t_event + timedelta(hours=1), window_days)
    assert h1[SERIES_ESCAPES] == [1.0]
    # A tick an hour later is still inside the same window → NO new observation.
    h_mid = loop._append_observations(t_event + timedelta(hours=2), window_days)
    assert h_mid[SERIES_ESCAPES] == [1.0]  # cursor did not advance


def test_windowing_single_event_counts_in_one_window_not_two(
    tmp_path: Path,
) -> None:
    window_days = 7
    t_event = datetime(2026, 5, 1, tzinfo=UTC)
    diag = tmp_path / "data" / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / "escape_ledger.jsonl").write_text(
        json.dumps({"id": "e0", "detected_at": t_event.isoformat()}) + "\n"
    )
    loop = _build_loop(tmp_path, _FakeState())

    loop._append_observations(t_event + timedelta(hours=1), window_days)
    # One full window later the trailing window no longer covers the event, so
    # the next disjoint observation reads 0.0 — never a second sustained 1.0.
    h2 = loop._append_observations(
        t_event + timedelta(days=window_days, hours=1), window_days
    )
    assert h2[SERIES_ESCAPES] == [1.0, 0.0]
