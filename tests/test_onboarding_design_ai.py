import pytest

from onboarding.design_ai import DesignAIService, apply_field_updates
from onboarding.models import BootstrapDraft, BootstrapSpec


def _draft(**overrides: object) -> BootstrapDraft:
    payload = {
        "name": "new-project",
        "description": "Dashboard-created project",
        "owner": "T-rav",
        "visibility": "private",
        "tech_stack": ["python"],
        "safety_guards": ["quality-gates"],
        "coverage_floor": 80,
        "label_prefix": "hydraflow",
        "main_branch": "main",
        "staging_branch": "staging",
    }
    payload.update(overrides)
    return BootstrapDraft(spec=BootstrapSpec.model_validate(payload))


@pytest.mark.asyncio
async def test_design_chat_extracts_six_core_fields() -> None:
    service = DesignAIService()

    turn = await service.chat(
        _draft(),
        (
            "Build ledger-lab as a public FastAPI React app for owner finance-org "
            "with Postgres, branch protection, deterministic tests, and 91% coverage."
        ),
    )

    assert turn.field_updates["name"] == "ledger-lab"
    assert turn.field_updates["owner"] == "finance-org"
    assert turn.field_updates["visibility"] == "public"
    assert turn.field_updates["coverage_floor"] == 91
    assert "FastAPI" in turn.field_updates["tech_stack"]
    assert "React" in turn.field_updates["tech_stack"]
    assert "branch-protection" in turn.field_updates["safety_guards"]
    assert "deterministic-tests" in turn.field_updates["safety_guards"]
    assert turn.clarification is None


def test_apply_field_updates_preserves_manual_fields() -> None:
    spec = _draft(package_name="ledger_lab", main_branch="trunk").spec

    updated = apply_field_updates(spec, {"name": "ledger-lab", "visibility": "public"})

    assert updated.name == "ledger-lab"
    assert updated.visibility == "public"
    assert updated.package_name == "ledger_lab"
    assert updated.main_branch == "trunk"


def test_spec_and_plan_adapt_to_ui_and_safety_choices() -> None:
    service = DesignAIService()
    draft = _draft(
        name="ledger-lab",
        tech_stack=["python", "FastAPI", "React"],
        safety_guards=["branch-protection", "decimal-purity"],
    )

    spec_text = service.draft_spec(draft, note="include boundaries")
    plan = service.draft_plan(draft)

    assert "## 10-file Invariant Kernel" in spec_text
    assert "## V1 IN" in spec_text
    assert "Revision note: include boundaries" in spec_text
    assert any("UI scaffold" in task for task in plan)
    assert any("branch-protection" in task for task in plan)
    assert any("decimal-purity" in task for task in plan)
