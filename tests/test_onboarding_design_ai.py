import pytest

from onboarding.design_ai import DesignAIService, apply_field_updates
from onboarding.models import BootstrapDraft, BootstrapSpec


@pytest.fixture(autouse=True)
def _disable_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_ONBOARDING_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


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


@pytest.mark.asyncio
async def test_design_chat_extraction_reliability_corpus() -> None:
    service = DesignAIService()
    messages = [
        "Build ledger-lab as a public FastAPI React app for owner finance-org with branch protection and 91% coverage.",
        "The repo is ledger-lab; org finance-org; open source; FastAPI API with React and branch protection, 91% test coverage.",
        "I want ledger-lab under organization finance-org, public, Python FastAPI plus React, branch protection, 91% coverage.",
        "Create ledger-lab owned by finance-org as public. Backend FastAPI, frontend React, branch protection, 91% coverage.",
        "Let's call it ledger-lab. Owner is finance-org. It should be public with FastAPI, React, branch protection, and 91% coverage.",
        "For owner finance-org, make public project ledger-lab using FastAPI and React; require branch protection and 91% coverage.",
        "ledger-lab should live under org finance-org; make it open source with FastAPI/React, branch protection, 91% coverage.",
        "Please draft ledger-lab for organization finance-org: public FastAPI service, React UI, branch protection, 91% coverage.",
        "Project ledger-lab, owner: finance-org, visibility public, stack Python + FastAPI + React, branch protection, 91% coverage.",
        "Use finance-org as owner for ledger-lab. Public repo, FastAPI backend, React UI, branch protection, 91% coverage.",
        "Bootstrap ledger-lab in org finance-org as public; FastAPI for the API, React for UI, branch protection, 91% coverage.",
        "Repo ledger-lab, owned by finance-org, is open-source. FastAPI and React, branch protection, 91% coverage.",
        "I need a public ledger-lab repository for owner finance-org; Python FastAPI, React, branch protection, 91% coverage.",
        "Make ledger-lab public for org finance-org. It uses FastAPI, has a React frontend, branch protection, 91% coverage.",
        "The app is ledger-lab, organization finance-org, public visibility, FastAPI backend, React UI, branch protection, 91% coverage.",
        "Start ledger-lab under the org finance-org. It is public, with FastAPI, React, branch protection, and 91% test coverage.",
        "I'd like ledger-lab owned by finance-org, public, FastAPI with React, branch protection enabled, 91% coverage.",
        "Configure ledger-lab for owner finance-org as a public FastAPI + React bootstrap with branch protection and 91% coverage.",
        "Set up ledger-lab; owner finance-org; public; API in FastAPI; React UI; branch protection; 91% coverage.",
        "finance-org owns ledger-lab. Make it public and use Python FastAPI, React, branch protection, 91% coverage.",
        "Build the public ledger-lab repo for org finance-org using FastAPI, React, branch protection, and 91% coverage.",
        "For finance-org, create ledger-lab as an open source FastAPI React service with branch protection and 91% coverage.",
        "ledger-lab is the name, finance-org is the owner, public is the visibility, stack FastAPI React, branch protection, 91% coverage.",
        "Use ledger-lab for the repo name under organization finance-org; public, FastAPI, React, branch protection, 91% coverage.",
        "Create a public FastAPI/React repo named ledger-lab for owner finance-org, with branch protection and 91% coverage.",
        "I am building ledger-lab for org finance-org: public repository, FastAPI backend, React app, branch protection, 91% coverage.",
        "Please make ledger-lab an open-source repo owned by finance-org; FastAPI + React; branch protection; 91% test coverage.",
        "ledger-lab should be public in organization finance-org, with FastAPI, React, branch protection, and 91% coverage.",
        "The target is ledger-lab, owner finance-org, public GitHub repo, FastAPI API, React client, branch protection, 91% coverage.",
        "Generate ledger-lab for owner finance-org as public; choose FastAPI, React, branch protection, and 91% coverage.",
    ]
    expected_checks = 0
    passed_checks = 0

    for message in messages:
        turn = await service.chat(_draft(), message)
        updates = turn.field_updates
        checks = [
            updates.get("name") == "ledger-lab",
            updates.get("owner") == "finance-org",
            updates.get("visibility") == "public",
            updates.get("coverage_floor") == 91,
            "FastAPI" in updates.get("tech_stack", []),
            "React" in updates.get("tech_stack", []),
            "branch-protection" in updates.get("safety_guards", []),
        ]
        expected_checks += len(checks)
        passed_checks += sum(1 for check in checks if check)

    assert len(messages) == 30
    assert passed_checks / expected_checks >= 0.95


@pytest.mark.asyncio
async def test_design_chat_revision_updates_sidebar_fields_within_one_turn() -> None:
    service = DesignAIService()
    draft = _draft(tech_stack=["python", "FastAPI", "Postgres", "React"])

    turn = await service.chat(
        draft,
        "Actually switch ledger-lab to SQLite and Next.js instead of Postgres and React.",
    )
    updated = apply_field_updates(draft.spec, turn.field_updates)

    assert "SQLite" in updated.tech_stack
    assert "Postgres" not in updated.tech_stack
    assert "Next.js" in updated.tech_stack
    assert "React" not in updated.tech_stack


@pytest.mark.asyncio
async def test_design_chat_surfaces_ambiguity_instead_of_guessing() -> None:
    service = DesignAIService()

    turn = await service.chat(
        _draft(tech_stack=["python", "FastAPI"]),
        "ledger-lab needs a UI, but I have not picked which one yet.",
    )

    assert (
        turn.clarification == "Do you want React, Next.js, or no UI for the bootstrap?"
    )
    assert "React" not in turn.field_updates.get("tech_stack", [])
    assert "Next.js" not in turn.field_updates.get("tech_stack", [])


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
