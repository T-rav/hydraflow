"""Unit tests for settling-window sensing (#10825, rung 1)."""

from __future__ import annotations

from stillness.settling import (
    Actuation,
    Reading,
    is_settling,
    partition_readings,
    settling_report,
)


def test_reading_within_the_window_after_actuation_is_settling() -> None:
    acts = [Actuation(area="edges", day=10)]
    assert is_settling("edges", 10, acts, window=3)  # same day
    assert is_settling("edges", 12, acts, window=3)  # 2 days later, inside
    assert not is_settling("edges", 13, acts, window=3)  # 3 days later, outside


def test_a_past_reading_is_not_perturbed_by_a_future_actuation() -> None:
    acts = [Actuation(area="edges", day=10)]
    assert not is_settling("edges", 9, acts, window=3)  # reading precedes the merge


def test_actuation_in_a_different_area_does_not_suppress() -> None:
    acts = [Actuation(area="edges", day=10)]
    assert not is_settling("adr-drift", 11, acts, window=3)


def test_partition_splits_signal_from_self_effect() -> None:
    acts = [Actuation(area="edges", day=10)]
    readings = [
        Reading("edges", 11, 5.0),  # inside window -> suppressed (self-effect)
        Reading("edges", 20, 5.0),  # outside window -> signal
        Reading("adr-drift", 11, 2.0),  # other area -> signal
    ]
    signal, suppressed = partition_readings(readings, acts, window=3)
    assert [r.day for r in suppressed] == [11]
    assert {(r.area, r.day) for r in signal} == {("edges", 20), ("adr-drift", 11)}


def test_report_counts_and_names_suppressed_areas() -> None:
    acts = [Actuation("edges", 10), Actuation("wiki-rot", 10)]
    readings = [
        Reading("edges", 11, 5.0),
        Reading("wiki-rot", 12, 3.0),
        Reading("adr-drift", 11, 2.0),
    ]
    report = settling_report(readings, acts, window=3)
    assert report.total == 3
    assert report.suppressed_count == 2
    assert report.signal_count == 1
    assert report.suppressed_areas == ("edges", "wiki-rot")  # sorted


def test_no_actuations_means_everything_is_signal() -> None:
    readings = [Reading("edges", 1, 5.0), Reading("edges", 2, 6.0)]
    report = settling_report(readings, [], window=3)
    assert report.suppressed_count == 0
    assert report.signal_count == 2
