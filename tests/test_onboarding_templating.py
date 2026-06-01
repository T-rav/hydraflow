"""Tests for onboarding repository templating."""

from __future__ import annotations

import pytest

from onboarding.models import BootstrapSpec
from onboarding.templating import MaterializeError, materialize_repository


def _spec(**overrides: object) -> BootstrapSpec:
    payload: dict[str, object] = {
        "name": "observability-tool",
        "description": "A repo for experimenting with observability workflows.",
        "owner": "T-rav",
        "visibility": "private",
        "tech_stack": ["python"],
        "safety_guards": ["decimal-purity"],
        "coverage_floor": 85,
        "label_prefix": "hydraflow",
    }
    payload.update(overrides)
    return BootstrapSpec.model_validate(payload)


def test_materialize_repository_writes_invariant_kernel(tmp_path) -> None:
    result = materialize_repository(_spec(), tmp_path)

    paths = {item.path for item in result.files}
    assert result.root == tmp_path / "observability-tool"
    assert "pyproject.toml" in paths
    assert "Makefile" in paths
    assert ".github/workflows/quality.yml" in paths
    assert "src/observability_tool/cli.py" in paths
    assert "tests/unit/test_smoke.py" in paths
    assert "scripts/setup_branch_protection.py" in paths
    assert "docs/specs/bootstrap-spec.md" in paths
    assert "docs/plans/plan-01-bootstrap.md" in paths

    pyproject = (result.root / "pyproject.toml").read_text()
    assert 'name = "observability-tool"' in pyproject
    assert 'venvPath = "."' in pyproject
    assert 'venv = ".venv"' in pyproject

    makefile = (result.root / "Makefile").read_text()
    assert "--cov-fail-under=85" in makefile
    assert "--decimal-purity" in makefile


def test_materialized_spec_and_plan_have_wizard_frontmatter(tmp_path) -> None:
    result = materialize_repository(_spec(), tmp_path)

    for relative_path in (
        "docs/specs/bootstrap-spec.md",
        "docs/plans/plan-01-bootstrap.md",
    ):
        content = (result.root / relative_path).read_text()
        assert content.startswith("---\nstatus: wizard-draft\n")
        assert "generated_by: hydraflow-wizard" in content
        assert "needs_refinement: true" in content
        assert "  - docs/methodology/onboarding-hydraflow-format-repos.md" in content


def test_materialize_refuses_non_empty_existing_target(tmp_path) -> None:
    target = tmp_path / "observability-tool"
    target.mkdir()
    (target / "README.md").write_text("existing")

    with pytest.raises(MaterializeError, match="already exists"):
        materialize_repository(_spec(), tmp_path)
