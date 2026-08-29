"""Unit tests for the charter schema + drift comparison (#11748, ADR-0143).

The rails half of these tests carries over unchanged from the ADR-0121
manifest they replace — the fold under ``rails:`` moves the fields, not their
semantics. The new coverage is the three things the charter adds: the
declarations (standards / artifacts), the two load-time rejections, and the
fail-loud guard against a drift check with nothing to check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from charter import (
    CHARTER_FILENAME,
    FINDING_COVERAGE_FLOOR,
    FINDING_LEGACY_RAILS_MANIFEST,
    FINDING_MISSING_ARTIFACT,
    FINDING_MISSING_GATE_SCRIPT,
    FINDING_MISSING_LAYER,
    FINDING_MISSING_STANDARD,
    FINDING_UNCHECKABLE_CHARTER,
    FINDING_UNKNOWN_LAYER,
    FINDING_UNKNOWN_STANDARD,
    LEGACY_RAILS_FILENAME,
    UNCHECKABLE_NOTHING_DECLARED,
    UNCHECKABLE_REGISTRY_UNAVAILABLE,
    Articles,
    Artifacts,
    Charter,
    CharterError,
    LocalArticle,
    ObservedRepo,
    Purpose,
    RailsBlock,
    charter_from_snapshot,
    compute_charter_drift,
    load_charter,
    render_charter,
    standard_ids_under,
    write_charter,
)

_ALL_LAYERS = ("universal", "language_pack", "domain_rails")
_STANDARDS = ("testing", "ports-and-loops")
_ARTIFACTS = ("docs/adr", "docs/arch/generated")


def _charter(**over) -> Charter:
    base = {
        "purpose": Purpose(product="a factory", goals=("lights_off",)),
        "articles": Articles(
            standards=_STANDARDS,
            assurance="internal",
            local=(
                LocalArticle(id="staging_only_prs", statement="PRs target staging"),
            ),
        ),
        "artifacts": Artifacts(required=_ARTIFACTS),
        "rails": RailsBlock(
            template_version="1.2.0",
            layers=_ALL_LAYERS,
            coverage_floor=70.0,
            domain_gate_scripts=("scan_secrets",),
        ),
    }
    base.update(over)
    return Charter(**base)


def _observed(**over) -> ObservedRepo:
    base = {
        "present_layers": frozenset(_ALL_LAYERS),
        "coverage": 85.0,
        "present_gate_scripts": frozenset({"scan_secrets"}),
        "present_standards": frozenset(_STANDARDS),
        "present_artifacts": frozenset(_ARTIFACTS),
        "known_standards": frozenset({*_STANDARDS, "adr_enforcement"}),
    }
    base.update(over)
    return ObservedRepo(**base)


def _classes(report) -> set[str]:
    return {f.finding_class for f in report.findings}


# --------------------------------------------------------------------------- #
# Schema — the four layers                                                     #
# --------------------------------------------------------------------------- #


def test_from_dict_loads_all_four_layers_plus_rails() -> None:
    charter = Charter.from_dict(
        {
            "purpose": {"product": "a factory", "goals": ["lights_off"]},
            "articles": {
                "standards": ["testing"],
                "assurance": "public-code",
                "local": [{"id": "x", "statement": "y"}],
            },
            "actors": "agents/",
            "artifacts": {"required": ["docs/adr"]},
            "rails": {"template_version": "2", "layers": ["universal"]},
        }
    )
    assert charter.purpose == Purpose(product="a factory", goals=("lights_off",))
    assert charter.articles.standards == ("testing",)
    assert charter.articles.assurance == "public-code"
    assert charter.articles.local == (LocalArticle(id="x", statement="y"),)
    assert charter.actors == "agents/"
    assert charter.artifacts.required == ("docs/adr",)
    assert charter.rails.template_version == "2"


def test_from_dict_tolerates_missing_keys() -> None:
    charter = Charter.from_dict({"rails": {"template_version": "2"}})
    assert charter.rails.template_version == "2"
    assert charter.articles.standards == ()
    assert charter.artifacts.required == ()
    assert charter.purpose == Purpose()


def test_to_dict_round_trips_through_from_dict() -> None:
    charter = _charter()
    assert Charter.from_dict(charter.to_dict()) == charter


def test_unknown_layers_detected() -> None:
    charter = _charter(
        rails=RailsBlock(layers=("universal", "operator_agent_pack", "language_pack"))
    )
    assert charter.rails.unknown_layers == ("operator_agent_pack",)


# --------------------------------------------------------------------------- #
# Load-time rejections — the two rulings that fail closed                      #
# --------------------------------------------------------------------------- #


def test_actors_path_pointer_is_accepted() -> None:
    assert Charter.from_dict({"actors": "agents/"}).actors == "agents/"


def test_actors_defaults_to_the_agents_tree_when_absent() -> None:
    assert Charter.from_dict({}).actors == "agents/"


def test_actors_role_list_is_rejected() -> None:
    with pytest.raises(CharterError) as exc:
        Charter.from_dict({"actors": ["arch", "design", "product"]})
    assert "agents/" in str(exc.value)


def test_actors_rejection_names_the_house_standard() -> None:
    with pytest.raises(CharterError, match="house standard"):
        Charter.from_dict({"actors": [{"role": "arch", "may": "approve"}]})


def test_actors_role_mapping_is_rejected_too() -> None:
    with pytest.raises(CharterError, match="Actors declaration"):
        Charter.from_dict({"actors": {"arch": "approves ADRs"}})


def test_assurance_outside_the_data_class_vocabulary_fails_closed() -> None:
    with pytest.raises(CharterError, match="not a data class"):
        Charter.from_dict({"articles": {"assurance": "high"}})


def test_assurance_regulated_class_is_accepted() -> None:
    charter = Charter.from_dict({"articles": {"assurance": "regulated-hipaa"}})
    assert charter.articles.assurance == "regulated-hipaa"


def test_assurance_defaults_to_internal() -> None:
    assert Charter.from_dict({}).articles.assurance == "internal"


# --------------------------------------------------------------------------- #
# Load / write                                                                 #
# --------------------------------------------------------------------------- #


def test_load_charter_absent_returns_none(tmp_path: Path) -> None:
    assert load_charter(tmp_path) is None


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    charter = _charter()
    path = write_charter(tmp_path, charter)
    assert path == tmp_path / CHARTER_FILENAME
    assert load_charter(tmp_path) == charter


def test_render_charter_has_header_comment() -> None:
    text = render_charter(_charter())
    assert text.lstrip().startswith("#")
    assert CHARTER_FILENAME in text


def test_legacy_rails_yaml_loads_as_a_rails_only_charter(tmp_path: Path) -> None:
    (tmp_path / LEGACY_RAILS_FILENAME).write_text(
        yaml.safe_dump({"template_version": "9", "layers": ["universal"]})
    )
    charter = load_charter(tmp_path)
    assert charter is not None
    assert charter.rails.template_version == "9"
    assert charter.articles.standards == ()


def test_legacy_rails_yaml_reports_a_non_fatal_finding(tmp_path: Path) -> None:
    (tmp_path / LEGACY_RAILS_FILENAME).write_text(
        yaml.safe_dump({"layers": ["universal"]})
    )
    charter = load_charter(tmp_path)
    assert charter is not None
    report = compute_charter_drift(
        charter, _observed(present_layers=frozenset({"universal"})), repo="o/r"
    )
    assert report.clean
    assert FINDING_LEGACY_RAILS_MANIFEST in _classes(report)


def test_charter_yaml_wins_over_a_legacy_rails_yaml(tmp_path: Path) -> None:
    write_charter(tmp_path, _charter())
    (tmp_path / LEGACY_RAILS_FILENAME).write_text(
        yaml.safe_dump({"template_version": "legacy"})
    )
    charter = load_charter(tmp_path)
    assert charter is not None
    assert charter.rails.template_version == "1.2.0"


def test_standard_ids_under_reads_directories_not_files(tmp_path: Path) -> None:
    (tmp_path / "docs" / "standards" / "testing").mkdir(parents=True)
    (tmp_path / "docs" / "standards" / "loose.md").write_text("#")
    assert standard_ids_under(tmp_path) == frozenset({"testing"})


# --------------------------------------------------------------------------- #
# Drift — the rails half, semantics unchanged from ADR-0121                    #
# --------------------------------------------------------------------------- #


def test_clean_when_observed_matches_charter() -> None:
    report = compute_charter_drift(_charter(), _observed(), repo="o/r")
    assert report.clean
    assert report.findings == ()


def test_missing_declared_layer_is_drift() -> None:
    observed = _observed(present_layers=frozenset({"universal", "domain_rails"}))
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert FINDING_MISSING_LAYER in _classes(report)


def test_undeclared_extra_rail_is_fine() -> None:
    charter = _charter(rails=RailsBlock(layers=("universal", "language_pack")))
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    assert report.clean


def test_unknown_future_layer_is_reported_not_fatal() -> None:
    charter = _charter(
        rails=RailsBlock(layers=("universal", "language_pack", "operator_agent_pack"))
    )
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    assert report.clean
    assert FINDING_UNKNOWN_LAYER in _classes(report)
    assert report.fatal_findings == ()


def test_coverage_floor_breach_is_drift() -> None:
    report = compute_charter_drift(_charter(), _observed(coverage=50.0), repo="o/r")
    assert FINDING_COVERAGE_FLOOR in _classes(report)


def test_coverage_unknown_never_flags_floor() -> None:
    report = compute_charter_drift(_charter(), _observed(coverage=None), repo="o/r")
    assert report.clean


def test_missing_domain_gate_script_is_drift() -> None:
    observed = _observed(present_gate_scripts=frozenset())
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert FINDING_MISSING_GATE_SCRIPT in _classes(report)


# --------------------------------------------------------------------------- #
# Drift — the charter half                                                     #
# --------------------------------------------------------------------------- #


def test_declared_standard_absent_from_the_repo_is_drift() -> None:
    observed = _observed(present_standards=frozenset({"ports-and-loops"}))
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert not report.clean
    assert FINDING_MISSING_STANDARD in _classes(report)


def test_missing_standard_check_id_names_the_standard() -> None:
    observed = _observed(present_standards=frozenset({"ports-and-loops"}))
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert any(f.check_id.endswith(":testing") for f in report.fatal_findings)


def test_unknown_standard_id_is_reported_not_fatal() -> None:
    charter = _charter(articles=Articles(standards=("soc2_ready",)))
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    assert report.clean
    assert FINDING_UNKNOWN_STANDARD in _classes(report)


def test_unknown_standard_is_still_reported_rather_than_swallowed() -> None:
    charter = _charter(articles=Articles(standards=("soc2_ready",)))
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    assert [f.check_id for f in report.tolerated_findings] == [
        f"{FINDING_UNKNOWN_STANDARD}:soc2_ready"
    ]


def test_undeclared_extra_standard_is_fine() -> None:
    charter = _charter(articles=Articles(standards=("testing",)))
    report = compute_charter_drift(charter, _observed(), repo="o/r")
    assert report.clean


def test_declared_required_artifact_absent_is_drift() -> None:
    observed = _observed(present_artifacts=frozenset({"docs/adr"}))
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert FINDING_MISSING_ARTIFACT in _classes(report)


def test_missing_artifact_check_id_names_the_path() -> None:
    observed = _observed(present_artifacts=frozenset({"docs/adr"}))
    report = compute_charter_drift(_charter(), observed, repo="o/r")
    assert any(
        f.check_id == f"{FINDING_MISSING_ARTIFACT}:docs/arch/generated"
        for f in report.fatal_findings
    )


# --------------------------------------------------------------------------- #
# The fail-loud guard: a check with nothing to check is not coverage           #
# --------------------------------------------------------------------------- #


def test_a_charter_declaring_nothing_checkable_is_fatal() -> None:
    report = compute_charter_drift(Charter(), ObservedRepo(), repo="o/r")
    assert not report.clean
    assert FINDING_UNCHECKABLE_CHARTER in _classes(report)


def test_nothing_declared_check_id_says_why() -> None:
    report = compute_charter_drift(Charter(), ObservedRepo(), repo="o/r")
    assert any(
        f.check_id.endswith(UNCHECKABLE_NOTHING_DECLARED) for f in report.fatal_findings
    )


def test_purpose_and_local_articles_alone_do_not_make_a_charter_checkable() -> None:
    charter = Charter(
        purpose=Purpose(product="a factory"),
        articles=Articles(local=(LocalArticle(id="x", statement="y"),)),
    )
    report = compute_charter_drift(charter, ObservedRepo(), repo="o/r")
    assert FINDING_UNCHECKABLE_CHARTER in _classes(report)


def test_one_declared_layer_is_enough_to_be_checkable() -> None:
    charter = Charter(rails=RailsBlock(layers=("universal",)))
    observed = ObservedRepo(present_layers=frozenset({"universal"}))
    report = compute_charter_drift(charter, observed, repo="o/r")
    assert report.clean


def test_an_unenumerable_standards_registry_is_fatal() -> None:
    report = compute_charter_drift(
        _charter(), _observed(known_standards=None), repo="o/r"
    )
    assert not report.clean
    assert any(
        f.check_id.endswith(UNCHECKABLE_REGISTRY_UNAVAILABLE)
        for f in report.fatal_findings
    )


def test_no_registry_and_no_declared_standards_needs_no_registry() -> None:
    charter = _charter(articles=Articles(standards=()))
    report = compute_charter_drift(charter, _observed(known_standards=None), repo="o/r")
    assert report.clean


# --------------------------------------------------------------------------- #
# Snapshot mapping                                                             #
# --------------------------------------------------------------------------- #


def test_charter_from_snapshot_maps_coverage_and_layers() -> None:
    charter = charter_from_snapshot(
        {"coverage_floor": 80.0, "tech_stack": "python", "template_version": "3"}
    )
    assert charter.rails.coverage_floor == 80.0
    assert "universal" in charter.rails.layers
    assert "language_pack" in charter.rails.layers
    assert "domain_rails" not in charter.rails.layers


def test_charter_from_snapshot_adds_domain_rails_when_present() -> None:
    charter = charter_from_snapshot({"coverage_floor": 70.0, "domain": "fintech"})
    assert "domain_rails" in charter.rails.layers


def test_charter_from_snapshot_declares_only_the_standards_it_is_given() -> None:
    charter = charter_from_snapshot({}, standards=("testing",))
    assert charter.articles.standards == ("testing",)


def test_charter_from_snapshot_declares_no_standards_by_default() -> None:
    assert charter_from_snapshot({}).articles.standards == ()


# --------------------------------------------------------------------------- #
# Malformed input: a declaration that cannot be read is not "no declaration"   #
# --------------------------------------------------------------------------- #


def test_a_charter_file_that_is_a_list_is_rejected(tmp_path: Path) -> None:
    (tmp_path / CHARTER_FILENAME).write_text("- one\n- two\n")
    with pytest.raises(CharterError, match="must be a YAML mapping"):
        load_charter(tmp_path)


def test_a_charter_file_that_is_unparseable_is_rejected(tmp_path: Path) -> None:
    (tmp_path / CHARTER_FILENAME).write_text("purpose: [unclosed\n")
    with pytest.raises(CharterError, match="not valid YAML"):
        load_charter(tmp_path)


def test_a_malformed_charter_is_not_reported_as_an_absent_one(tmp_path: Path) -> None:
    (tmp_path / CHARTER_FILENAME).write_text("just a string\n")
    with pytest.raises(CharterError):
        load_charter(tmp_path)


def test_a_malformed_legacy_rails_file_is_rejected(tmp_path: Path) -> None:
    (tmp_path / LEGACY_RAILS_FILENAME).write_text("- one\n")
    with pytest.raises(CharterError, match="must be a YAML mapping"):
        load_charter(tmp_path)


def test_standards_given_as_a_mapping_is_rejected() -> None:
    with pytest.raises(CharterError, match="must be a list"):
        Charter.from_dict({"articles": {"standards": {"testing": True}}})


def test_standards_given_as_a_bare_string_is_rejected() -> None:
    with pytest.raises(CharterError, match="must be a list"):
        Charter.from_dict({"articles": {"standards": "testing"}})


def test_a_local_article_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(CharterError, match="must be a mapping"):
        Charter.from_dict({"articles": {"local": ["staging_only_prs"]}})


def test_an_absolute_required_artifact_is_rejected() -> None:
    with pytest.raises(CharterError, match="relative to the repo root"):
        Charter.from_dict({"artifacts": {"required": ["/etc/passwd"]}})


def test_a_required_artifact_escaping_the_repo_is_rejected() -> None:
    with pytest.raises(CharterError, match="relative to the repo root"):
        Charter.from_dict({"artifacts": {"required": ["../other-repo/docs"]}})
