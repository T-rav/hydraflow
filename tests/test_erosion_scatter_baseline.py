"""Unit tests for the concept-scatter baseline (Set-point) load/save/diff ratchet."""

from __future__ import annotations

from pathlib import Path

from erosion.models import ScatteredSymbol, ScatterFinding
from erosion.scatter_baseline import (
    diff,
    load_scatter_baseline,
    save_scatter_baseline,
)


def _finding(*symbols: tuple[str, int]) -> ScatterFinding:
    scattered = tuple(
        ScatteredSymbol(
            symbol=name,
            modules=tuple(f"src.m{i}" for i in range(count)),
            files=tuple(f"src/m{i}/f.py" for i in range(count)),
        )
        for name, count in symbols
    )
    return ScatterFinding(scattered=scattered, threshold=3, unmapped_files=())


def test_load_missing_baseline_returns_empty(tmp_path: Path) -> None:
    baseline = load_scatter_baseline(tmp_path / "nope.yaml")

    assert baseline == {}


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "concept_scatter.yaml"
    finding = _finding(("do_thing", 3), ("other_thing", 4))

    save_scatter_baseline(p, finding, comment="observed norm over last N merges")

    loaded = load_scatter_baseline(p)
    assert loaded == {"do_thing": 3, "other_thing": 4}
    raw = p.read_text(encoding="utf-8")
    assert "observed norm over last N merges" in raw


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "dir" / "concept_scatter.yaml"
    finding = _finding(("do_thing", 3))

    save_scatter_baseline(p, finding, comment="c")

    assert p.exists()
    assert load_scatter_baseline(p) == {"do_thing": 3}


def test_diff_flags_new_symbol_not_in_baseline() -> None:
    finding = _finding(("do_thing", 3))

    result = diff(finding, {})

    assert result.new == {"do_thing": 3}
    assert result.resolved == {}
    assert result.unchanged == ()


def test_diff_flags_worsening_symbol_with_excess_modules() -> None:
    finding = _finding(("do_thing", 5))

    result = diff(finding, {"do_thing": 3})

    assert result.new == {"do_thing": 2}


def test_diff_reports_unchanged_when_scatter_degree_matches_baseline() -> None:
    finding = _finding(("do_thing", 3))

    result = diff(finding, {"do_thing": 3})

    assert result.new == {}
    assert result.resolved == {}
    assert result.unchanged == ("do_thing",)


def test_diff_reports_resolved_when_symbol_no_longer_scattered() -> None:
    # "do_thing" dropped below threshold this run and no longer appears in
    # `finding.scattered` at all (current count is implicitly 0).
    finding = _finding()

    result = diff(finding, {"do_thing": 3})

    assert result.resolved == {"do_thing": 3}
    assert result.new == {}


def test_diff_reports_resolved_when_symbol_scatter_shrinks_but_still_flagged() -> None:
    finding = _finding(("do_thing", 3))

    result = diff(finding, {"do_thing": 5})

    assert result.resolved == {"do_thing": 2}
