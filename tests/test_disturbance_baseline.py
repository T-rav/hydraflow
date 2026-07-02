"""Unit tests for baseline load/save/diff (count-per-signature ratchet)."""

from __future__ import annotations

from pathlib import Path

from disturbance.baseline import diff, load_baseline, save_baseline
from disturbance.models import Finding


def _f(sig: str) -> Finding:
    return Finding(
        dimension="d", path=sig.split("::", maxsplit=1)[0], signature=sig, message="m"
    )


def test_save_then_load_round_trips_counts(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    save_baseline(
        p,
        [_f("src/a.py::noqa"), _f("src/a.py::noqa"), _f("src/b.py::type-ignore")],
        comment="c",
    )
    assert load_baseline(p) == {"src/a.py::noqa": 2, "src/b.py::type-ignore": 1}


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "nope.yaml") == {}


def test_diff_flags_increase_as_new() -> None:
    r = diff([_f("s::x"), _f("s::x")], {"s::x": 1})
    assert r.new == {"s::x": 1}  # one more than baseline
    assert r.resolved == {}
    assert r.unchanged == ()


def test_diff_flags_decrease_as_resolved() -> None:
    r = diff([_f("s::x")], {"s::x": 3})
    assert r.new == {}
    assert r.resolved == {"s::x": 2}  # two fewer than baseline -> must prune
    assert r.unchanged == ()


def test_diff_equal_counts_unchanged() -> None:
    r = diff([_f("s::x"), _f("s::x")], {"s::x": 2})
    assert r.new == {} and r.resolved == {}
    assert r.unchanged == ("s::x",)
