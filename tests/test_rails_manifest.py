"""Unit tests for the rails manifest schema + drift comparison (#10936, ADR-0121)."""

from __future__ import annotations

from pathlib import Path

from rails_manifest import (
    FINDING_COVERAGE_FLOOR,
    FINDING_MISSING_GATE_SCRIPT,
    FINDING_MISSING_LAYER,
    FINDING_UNKNOWN_LAYER,
    ObservedRails,
    RailsManifest,
    compute_rails_drift,
    load_manifest,
    manifest_from_snapshot,
    render_manifest,
    write_manifest,
)

_ALL_LAYERS = ("universal", "language_pack", "domain_rails")


def _manifest(**over) -> RailsManifest:
    base = {
        "template_version": "1.2.0",
        "layers": _ALL_LAYERS,
        "coverage_floor": 70.0,
        "domain_gate_scripts": ("scan_secrets",),
    }
    base.update(over)
    return RailsManifest(**base)


def _observed(**over) -> ObservedRails:
    base = {
        "present_layers": frozenset(_ALL_LAYERS),
        "coverage": 85.0,
        "present_gate_scripts": frozenset({"scan_secrets"}),
    }
    base.update(over)
    return ObservedRails(**base)


# --------------------------------------------------------------------------- #
# Schema                                                                       #
# --------------------------------------------------------------------------- #


def test_from_dict_tolerates_missing_keys() -> None:
    m = RailsManifest.from_dict({"template_version": "2"})
    assert m.template_version == "2"
    assert m.layers == ()
    assert m.coverage_floor == 0.0
    assert m.domain_gate_scripts == ()


def test_to_dict_round_trips_through_from_dict() -> None:
    m = _manifest()
    assert RailsManifest.from_dict(m.to_dict()) == m


def test_unknown_layers_detected() -> None:
    m = _manifest(layers=("universal", "operator_agent_pack", "language_pack"))
    assert m.unknown_layers == ("operator_agent_pack",)


# --------------------------------------------------------------------------- #
# Load / write                                                                 #
# --------------------------------------------------------------------------- #


def test_load_manifest_absent_returns_none(tmp_path: Path) -> None:
    assert load_manifest(tmp_path / "rails.yaml") is None


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    m = _manifest()
    path = write_manifest(tmp_path, m)
    assert path == tmp_path / "rails.yaml"
    assert load_manifest(path) == m


def test_render_manifest_has_header_comment() -> None:
    text = render_manifest(_manifest())
    assert text.lstrip().startswith("#")
    assert "rails.yaml" in text


# --------------------------------------------------------------------------- #
# Drift computation                                                            #
# --------------------------------------------------------------------------- #


def test_clean_when_observed_matches_manifest() -> None:
    report = compute_rails_drift(_manifest(), _observed(), repo="o/r")
    assert report.clean
    assert report.findings == ()


def test_missing_declared_layer_is_drift() -> None:
    observed = _observed(present_layers=frozenset({"universal", "domain_rails"}))
    report = compute_rails_drift(_manifest(), observed, repo="o/r")
    assert not report.clean
    classes = {f.finding_class for f in report.findings}
    assert FINDING_MISSING_LAYER in classes
    assert any("language_pack" in f.check_id for f in report.findings)


def test_undeclared_extra_rail_is_fine() -> None:
    # Repo carries an extra layer the manifest never declared — not drift.
    m = _manifest(layers=("universal", "language_pack"))
    observed = _observed(present_layers=frozenset(_ALL_LAYERS))
    report = compute_rails_drift(m, observed, repo="o/r")
    assert report.clean


def test_unknown_future_layer_is_reported_not_fatal() -> None:
    # A future layer name (Book-3 operator-agent pack) is tolerated: reported
    # as a finding but clean stays True and it is not a fatal finding.
    m = _manifest(layers=("universal", "language_pack", "operator_agent_pack"))
    report = compute_rails_drift(m, _observed(), repo="o/r")
    assert report.clean  # not fatal
    assert any(f.finding_class == FINDING_UNKNOWN_LAYER for f in report.findings)
    assert report.tolerated_unknown_layers == ("operator_agent_pack",)
    assert report.fatal_findings == ()


def test_coverage_floor_breach_is_drift() -> None:
    report = compute_rails_drift(_manifest(), _observed(coverage=50.0), repo="o/r")
    assert not report.clean
    assert any(f.finding_class == FINDING_COVERAGE_FLOOR for f in report.findings)


def test_coverage_unknown_never_flags_floor() -> None:
    # Fail-open: coverage we could not measure must not file drift.
    report = compute_rails_drift(_manifest(), _observed(coverage=None), repo="o/r")
    assert report.clean


def test_missing_domain_gate_script_is_drift() -> None:
    observed = _observed(present_gate_scripts=frozenset())
    report = compute_rails_drift(_manifest(), observed, repo="o/r")
    assert not report.clean
    assert any(f.finding_class == FINDING_MISSING_GATE_SCRIPT for f in report.findings)


# --------------------------------------------------------------------------- #
# Snapshot mapping                                                             #
# --------------------------------------------------------------------------- #


def test_manifest_from_snapshot_maps_coverage_and_layers() -> None:
    m = manifest_from_snapshot(
        {"coverage_floor": 80.0, "tech_stack": "python", "template_version": "3"}
    )
    assert m.coverage_floor == 80.0
    assert "universal" in m.layers
    assert "language_pack" in m.layers
    # No domain declared → no domain_rails layer.
    assert "domain_rails" not in m.layers


def test_manifest_from_snapshot_adds_domain_rails_when_present() -> None:
    m = manifest_from_snapshot({"coverage_floor": 70.0, "domain": "fintech"})
    assert "domain_rails" in m.layers
