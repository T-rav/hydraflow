"""Unit tests for SecondOrderVitalsLoop (#10373).

Covers the read-only Pattern-B tick end to end with the instrument readings
injected (``gather_series_readings`` monkeypatched) and the primary-health gate
injected: diverging → exactly ONE find + HITL escalation on the episode edge
(never re-filed within the episode), watch → no issue, primary-not-green
suppresses the alarm, the config kill-switch, and the deterministic report +
``vitals.jsonl`` writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import second_order_vitals_loop as loop_mod
from second_order_vitals_loop import SecondOrderVitalsLoop
from tests.helpers import make_bg_loop_deps
from vitals.models import (
    SERIES_AUDIT_DISAGREEMENT,
    SERIES_ESCAPES,
    SERIES_INTERVENTION_CORRECTIONS,
)
from vitals.observe import PrimaryHealth

_THREE = (SERIES_ESCAPES, SERIES_INTERVENTION_CORRECTIONS, SERIES_AUDIT_DISAGREEMENT)
_TWO = (SERIES_ESCAPES, SERIES_INTERVENTION_CORRECTIONS)


class _FakeState:
    """In-memory backing for the two vitals state fields."""

    def __init__(
        self, history: dict[str, list[float]] | None = None, last: str = ""
    ) -> None:
        self._history = {k: list(v) for k, v in (history or {}).items()}
        self._last = last

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


class _FakePR:
    """Records create_issue calls; returns incrementing issue numbers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        self.calls.append({"title": title, "body": body, "labels": labels or []})
        return len(self.calls)


def _green(_now: Any, _window_days: int) -> PrimaryHealth:
    return PrimaryHealth(ci_pass_rate=1.0, merge_throughput=100)


def _red(_now: Any, _window_days: int) -> PrimaryHealth:
    return PrimaryHealth(ci_pass_rate=0.0, merge_throughput=0)


def _build_loop(
    tmp_path: Path,
    *,
    state: _FakeState,
    prs: _FakePR,
    reader: Any = _green,
    enabled: bool = True,
    loop_enabled: bool = True,
) -> SecondOrderVitalsLoop:
    bg = make_bg_loop_deps(tmp_path, enabled=enabled)
    c = bg.config
    # ConfigFactory.create has a fixed signature (no vitals knobs), so set the
    # thresholds directly on the frozen config for a small, fast baseline.
    for field, value in {
        "data_root": tmp_path / "data",
        "dry_run": False,
        "second_order_vitals_loop_enabled": loop_enabled,
        "second_order_vitals_min_baseline_windows": 3,
        "second_order_vitals_sustained_windows": 2,
        "second_order_vitals_watch_k": 2,
        "second_order_vitals_diverging_k": 3,
    }.items():
        object.__setattr__(c, field, value)
    return SecondOrderVitalsLoop(
        config=c,
        pr_manager=prs,
        state=state,
        deps=bg.loop_deps,
        primary_health_reader=reader,
    )


def _readings(series: tuple[str, ...], value: float) -> dict[str, float | None]:
    return dict.fromkeys(series, value)


def _patch_readings(
    monkeypatch: pytest.MonkeyPatch, series: tuple[str, ...], value: float
) -> None:
    monkeypatch.setattr(
        loop_mod,
        "gather_series_readings",
        lambda _config, *, now, window_days: _readings(series, value),
    )


class TestKillSwitch:
    async def test_config_disabled_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _THREE, 10.0)
        loop = _build_loop(
            tmp_path, state=_FakeState(), prs=_FakePR(), loop_enabled=False
        )
        result = await loop._do_work()
        assert result == {"status": "config_disabled"}


class TestDivergingAlarm:
    async def test_diverging_edge_files_one_find_and_hitl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _THREE, 10.0)
        # Pre-seed each family's series one window short of a sustained breach;
        # this tick's appended high reading completes the second sustained window.
        state = _FakeState({name: [0.0, 0.0, 0.0, 10.0] for name in _THREE}, last="")
        prs = _FakePR()
        loop = _build_loop(tmp_path, state=state, prs=prs)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["verdict"] == "diverging"
        assert result["k"] == 3
        assert result["filed"] == 1
        assert len(prs.calls) == 1
        labels = prs.calls[0]["labels"]
        assert "hydraflow-find" in labels
        assert "second-order-vitals" in labels
        assert "hydraflow-hitl-escalation" in labels
        assert state.get_second_order_vitals_last_verdict() == "diverging"

    async def test_no_refile_within_open_episode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _THREE, 10.0)
        # Episode already open (last verdict diverging): a still-diverging tick
        # must NOT re-file — the alarm fires once per episode, never every tick.
        state = _FakeState(
            {name: [0.0, 0.0, 0.0, 10.0] for name in _THREE}, last="diverging"
        )
        prs = _FakePR()
        loop = _build_loop(tmp_path, state=state, prs=prs)

        result = await loop._do_work()

        assert result["verdict"] == "diverging"
        assert result["filed"] == 0
        assert prs.calls == []

    async def test_primary_not_green_suppresses_alarm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _THREE, 10.0)
        state = _FakeState({name: [0.0, 0.0, 0.0, 10.0] for name in _THREE}, last="")
        prs = _FakePR()
        loop = _build_loop(tmp_path, state=state, prs=prs, reader=_red)

        result = await loop._do_work()

        assert result["verdict"] == "green"
        assert result["primary_health_green"] is False
        assert prs.calls == []


class TestWatchIsSilent:
    async def test_watch_files_no_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _TWO, 10.0)
        state = _FakeState({name: [0.0, 0.0, 0.0, 10.0] for name in _TWO}, last="")
        prs = _FakePR()
        loop = _build_loop(tmp_path, state=state, prs=prs)

        result = await loop._do_work()

        assert result["verdict"] == "watch"
        assert result["k"] == 2
        assert result["filed"] == 0
        assert prs.calls == []
        # watch is a dashboard state change only — the verdict is still persisted.
        assert state.get_second_order_vitals_last_verdict() == "watch"


class TestSelfModificationClass:
    """The monitor's own files must be self-modification class (#10371/#10373).

    The monitor for green-while-dying must not be quietly editable by the
    machinery it monitors — a change to its loop, its pure engine, or its state
    accessor is the highest blast-radius class (independent verdict, fail-closed).
    """

    def test_loop_files_classify_as_self_modification(self) -> None:
        import judge_independence as ji

        for path in (
            "src/second_order_vitals_loop.py",
            "src/vitals/verdict.py",
            "src/vitals/control.py",
            "src/state/_second_order_vitals.py",
        ):
            classes = ji.classify_paths([path])
            assert ji.is_self_modification(classes), path


class TestSurfaces:
    async def test_report_and_vitals_history_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_readings(monkeypatch, _THREE, 10.0)
        state = _FakeState({name: [0.0, 0.0, 0.0, 10.0] for name in _THREE}, last="")
        loop = _build_loop(tmp_path, state=state, prs=_FakePR())

        await loop._do_work()

        report = tmp_path / "repo" / "docs/arch/generated/second-order-vitals.md"
        assert report.exists()
        text = report.read_text()
        assert "Second-order vitals" in text
        assert "diverging" in text
        vitals = tmp_path / "data" / "diagnostics" / "vitals.jsonl"
        assert vitals.exists()
        assert '"verdict": "diverging"' in vitals.read_text()
