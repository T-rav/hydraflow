"""Unit tests for the vitals-methodology arch surface (ADR-0133 wiring, #10838)."""

from __future__ import annotations

from arch.generators.vitals_methodology_report import render_vitals_methodology


def test_current_fleet_renders_at_the_three_sigma_floor() -> None:
    # The live second-order fleet is 8 series; at a 5% budget that computes
    # below 3σ, so the surface must report the floor, not a widened limit.
    out = render_vitals_methodology()
    assert "# Vitals Methodology (ADR-0133)" in out
    assert "3.000σ" in out
    assert "at the 3σ floor" in out
    assert "does not need widening yet" in out


def test_large_fleet_reports_a_widened_limit_above_three_sigma() -> None:
    # Inject a fleet big enough to lift off the floor: the status flips.
    out = render_vitals_methodology(series_count=70)
    assert "widened above 3σ" in out
    assert "at the 3σ floor" not in out
    # 70 charts at 5% → ~3.4σ (the ADR headline).
    assert "3.384σ" in out


def test_readiness_projection_shows_the_floor_lifting() -> None:
    out = render_vitals_methodology()
    # The curve must include the crossover: floored below ~19, widened at/above.
    assert "| 15 | 3.000σ | floored |" in out
    assert "| 19 | 3.008σ | yes |" in out
    assert "| 70 | 3.384σ | yes |" in out


def test_current_marker_tracks_the_injected_fleet_size() -> None:
    assert "| 8 ← current |" in render_vitals_methodology()
    assert "| 70 ← current |" in render_vitals_methodology(series_count=70)


def test_published_mde_table_is_rendered() -> None:
    out = render_vitals_methodology()
    assert "| 2× | 11 |" in out
    assert "| 1.1× | 824 |" in out
    assert "| 0.5× | 23 |" in out


def test_scarce_event_section_flags_the_escapes_series() -> None:
    out = render_vitals_methodology()
    assert "Scarce-event metrics" in out
    assert "escapes per window" in out
    assert "merges-between-escapes" in out


def test_surface_is_deterministic_and_carries_the_arch_footer() -> None:
    first = render_vitals_methodology()
    assert render_vitals_methodology() == first  # pure function of static inputs
    assert first.rstrip().endswith("{{ARCH_FOOTER}}")


def test_surface_changes_no_live_threshold_claim_is_present() -> None:
    # The surface must be explicit that it is read-only (no live threshold moved).
    assert "No live threshold is changed" in render_vitals_methodology()
