"""Unit tests for the change-spread baseline (Set-point) load/save/is_flagged."""

from __future__ import annotations

from pathlib import Path

from erosion.baseline import (
    DEFAULT_MAX_SPREAD_RATIO,
    SpreadBaseline,
    is_flagged,
    load_spread_baseline,
    save_spread_baseline,
)
from erosion.models import SpreadFinding


def _finding(files: int, modules: int) -> SpreadFinding:
    return SpreadFinding(
        files_touched=files,
        modules_crossed=modules,
        modules=tuple(f"src.m{i}" for i in range(modules)),
        unmapped_files=(),
    )


def test_load_missing_baseline_returns_default(tmp_path: Path) -> None:
    baseline = load_spread_baseline(tmp_path / "nope.yaml")

    assert baseline.max_spread_ratio == DEFAULT_MAX_SPREAD_RATIO
    assert baseline.comment == ""


def test_load_missing_baseline_honors_explicit_default(tmp_path: Path) -> None:
    baseline = load_spread_baseline(tmp_path / "nope.yaml", default=0.35)

    assert baseline.max_spread_ratio == 0.35


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "change_spread.yaml"
    save_spread_baseline(p, 0.6, comment="observed norm over last N merges")

    loaded = load_spread_baseline(p)

    assert loaded.max_spread_ratio == 0.6
    assert loaded.comment == "observed norm over last N merges"


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "dir" / "change_spread.yaml"
    save_spread_baseline(p, 0.5, comment="c")

    assert p.exists()
    assert load_spread_baseline(p).max_spread_ratio == 0.5


def test_low_spread_finding_not_flagged() -> None:
    finding = _finding(files=10, modules=2)  # ratio 0.2

    assert not is_flagged(finding, SpreadBaseline(max_spread_ratio=0.5))


def test_high_spread_finding_flagged() -> None:
    finding = _finding(files=4, modules=4)  # ratio 1.0

    assert is_flagged(finding, SpreadBaseline(max_spread_ratio=0.5))


def test_finding_exactly_at_baseline_is_not_flagged() -> None:
    finding = _finding(files=4, modules=2)  # ratio 0.5

    assert not is_flagged(finding, SpreadBaseline(max_spread_ratio=0.5))
