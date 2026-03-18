"""Tests for risk model module."""

from __future__ import annotations

from risk_model import (
    RiskDimensions,
    RiskScore,
    _compute_blast_radius,
    _detect_config_touch,
    _level_from_score,
    assess_risk,
)


class TestLevelFromScore:
    def test_low(self) -> None:
        assert _level_from_score(0.0) == "low"
        assert _level_from_score(0.24) == "low"

    def test_medium(self) -> None:
        assert _level_from_score(0.25) == "medium"
        assert _level_from_score(0.49) == "medium"

    def test_high(self) -> None:
        assert _level_from_score(0.50) == "high"
        assert _level_from_score(0.74) == "high"

    def test_critical(self) -> None:
        assert _level_from_score(0.75) == "critical"
        assert _level_from_score(1.0) == "critical"


class TestComputeBlastRadius:
    def test_empty_files(self) -> None:
        assert _compute_blast_radius([]) == "isolated"

    def test_single_directory(self) -> None:
        assert _compute_blast_radius(["src/foo.py", "src/bar.py"]) == "isolated"

    def test_two_directories(self) -> None:
        assert _compute_blast_radius(["src/foo.py", "tests/test_foo.py"]) == "module"

    def test_four_directories(self) -> None:
        files = ["src/a.py", "tests/b.py", "docs/c.md", "scripts/d.sh"]
        assert _compute_blast_radius(files) == "cross-cutting"

    def test_infrastructure_patterns(self) -> None:
        assert _compute_blast_radius(["Dockerfile"]) == "infrastructure"
        assert _compute_blast_radius([".github/workflows/ci.yml"]) == "infrastructure"
        assert _compute_blast_radius(["terraform/main.tf"]) == "infrastructure"

    def test_infra_takes_precedence(self) -> None:
        files = ["src/foo.py", ".github/workflows/ci.yml"]
        assert _compute_blast_radius(files) == "infrastructure"


class TestDetectConfigTouch:
    def test_env_file(self) -> None:
        assert _detect_config_touch([".env"]) is True

    def test_pyproject_toml(self) -> None:
        assert _detect_config_touch(["pyproject.toml"]) is True

    def test_package_json(self) -> None:
        assert _detect_config_touch(["package.json"]) is True

    def test_no_config(self) -> None:
        assert _detect_config_touch(["src/main.py"]) is False


class TestAssessRisk:
    def test_tests_only_reduces_risk(self) -> None:
        result = assess_risk(RiskDimensions(touches_tests_only=True))
        assert result.score == 0.0
        assert result.level == "low"
        assert any("-0.30" in f for f in result.factors)

    def test_high_risk_paths(self) -> None:
        result = assess_risk(RiskDimensions(high_risk_paths_touched=True))
        assert result.score >= 0.25
        assert "high-risk" in result.factors[0]

    def test_large_diff(self) -> None:
        result = assess_risk(RiskDimensions(diff_line_count=1500))
        assert result.score >= 0.20

    def test_medium_diff(self) -> None:
        result = assess_risk(RiskDimensions(diff_line_count=600))
        assert result.score >= 0.10

    def test_many_files(self) -> None:
        files = [f"src/file_{i}.py" for i in range(30)]
        result = assess_risk(RiskDimensions(files_changed=files))
        assert result.score >= 0.20

    def test_config_touch(self) -> None:
        result = assess_risk(RiskDimensions(touches_config=True))
        assert result.score >= 0.15

    def test_config_auto_detected(self) -> None:
        result = assess_risk(RiskDimensions(files_changed=[".env"]))
        assert result.score >= 0.15

    def test_epic_child(self) -> None:
        result = assess_risk(RiskDimensions(is_epic_child=True))
        assert result.score >= 0.05

    def test_critical_scanning(self) -> None:
        result = assess_risk(RiskDimensions(code_scanning_severity_max="critical"))
        assert result.score >= 0.30

    def test_high_scanning(self) -> None:
        result = assess_risk(RiskDimensions(code_scanning_severity_max="high"))
        assert result.score >= 0.15

    def test_visual_triggers(self) -> None:
        result = assess_risk(
            RiskDimensions(
                visual_triggers=["color-change", "layout-shift", "new-element"]
            )
        )
        assert result.score >= 0.15

    def test_visual_trigger_capped(self) -> None:
        triggers = [f"trigger-{i}" for i in range(10)]
        result = assess_risk(RiskDimensions(visual_triggers=triggers))
        # Visual triggers capped at +0.15
        visual_factor = [f for f in result.factors if "visual" in f]
        assert len(visual_factor) == 1
        assert "+0.15" in visual_factor[0]

    def test_issue_type_feature(self) -> None:
        result = assess_risk(RiskDimensions(issue_type="feature"))
        assert result.score >= 0.10

    def test_issue_type_chore(self) -> None:
        result = assess_risk(RiskDimensions(issue_type="chore"))
        assert result.score == 0.0

    def test_score_capped_at_one(self) -> None:
        dims = RiskDimensions(
            high_risk_paths_touched=True,
            diff_line_count=2000,
            files_changed=[f"dir{i}/f.py" for i in range(30)],
            touches_config=True,
            code_scanning_severity_max="critical",
            visual_triggers=["a", "b", "c"],
            issue_type="feature",
            is_epic_child=True,
        )
        result = assess_risk(dims)
        assert result.score <= 1.0
        assert result.level == "critical"

    def test_returns_risk_score_model(self) -> None:
        result = assess_risk(RiskDimensions())
        assert isinstance(result, RiskScore)
        assert isinstance(result.factors, list)
        assert result.blast_radius in (
            "isolated",
            "module",
            "cross-cutting",
            "infrastructure",
        )
