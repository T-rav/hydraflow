"""Tests for the headless onboarding draft API."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from onboarding.design_ai import (
    AnthropicDesignProvider,
    DesignAIService,
    DesignProviderError,
    DesignTurn,
)
from onboarding.models import (
    BootstrapDraft,
    BootstrapSpec,
    ContinuePlanRequest,
    DesignChatRequest,
    DesignRevisionRequest,
    MaterializeRequest,
)
from tests.helpers import find_endpoint, make_dashboard_router


def _spec_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "observability-tool",
        "description": "A repo for experimenting with observability workflows.",
        "owner": "T-rav",
        "visibility": "private",
        "tech_stack": ["python", "python", "react"],
        "safety_guards": ["branch-protection"],
        "coverage_floor": 85,
    }
    payload.update(overrides)
    return payload


class TestBootstrapSpec:
    def test_normalizes_project_name_and_dedupes_stack(self) -> None:
        spec = BootstrapSpec.model_validate(_spec_payload(name="Observability-Tool"))

        assert spec.name == "observability-tool"
        assert spec.tech_stack == ["python", "react"]

    def test_rejects_non_kebab_project_name(self) -> None:
        with pytest.raises(ValidationError, match="name must be lowercase kebab-case"):
            BootstrapSpec.model_validate(_spec_payload(name="bad name"))


class TestOnboardingDraftRoutes:
    def test_routes_are_registered(self, config, event_bus, state, tmp_path) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}

        assert "/api/onboarding/drafts" in paths
        assert "/api/onboarding/drafts/{draft_id}" in paths
        assert "/api/onboarding/drafts/{draft_id}/design/chat" in paths
        assert "/api/onboarding/drafts/{draft_id}/design/spec" in paths
        assert "/api/onboarding/drafts/{draft_id}/design/plan" in paths
        assert "/api/onboarding/drafts/{draft_id}/continue-plan" in paths
        assert "/api/onboarding/drafts/{draft_id}/materialize" in paths
        assert "/api/onboarding/drafts/{draft_id}/push" in paths

    @pytest.mark.asyncio
    async def test_create_draft_persists_state(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/onboarding/drafts", method="POST")

        response = await endpoint(BootstrapSpec.model_validate(_spec_payload()))
        data = json.loads(response.body)

        assert response.status_code == 201
        assert data["status"] == "draft"
        assert data["spec"]["name"] == "observability-tool"
        assert data["materialize_status"] == "not_started"
        assert state.get_onboarding_draft(data["id"])["id"] == data["id"]

    @pytest.mark.asyncio
    async def test_get_draft_returns_persisted_state(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="writing-tool"))
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/onboarding/drafts/{draft_id}")

        response = await endpoint(draft.id)
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["id"] == draft.id
        assert data["spec"]["name"] == "writing-tool"

    @pytest.mark.asyncio
    async def test_get_draft_404s_for_unknown_id(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/onboarding/drafts/{draft_id}")

        response = await endpoint("missing")

        assert response.status_code == 404
        assert json.loads(response.body)["error"] == "Draft not found"

    @pytest.mark.asyncio
    async def test_list_drafts_returns_newest_first(
        self, config, event_bus, state, tmp_path
    ) -> None:
        older = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="older-tool")),
            created_at="2026-05-20T00:00:00+00:00",
            updated_at="2026-05-20T00:00:00+00:00",
        )
        newer = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="newer-tool")),
            created_at="2026-05-21T00:00:00+00:00",
            updated_at="2026-05-21T00:00:00+00:00",
        )
        state.set_onboarding_draft(older.id, older.model_dump(mode="json"))
        state.set_onboarding_draft(newer.id, newer.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/onboarding/drafts", method="GET")

        response = await endpoint()
        data = json.loads(response.body)

        assert [draft["spec"]["name"] for draft in data["drafts"]] == [
            "newer-tool",
            "older-tool",
        ]

    @pytest.mark.asyncio
    async def test_materialize_draft_writes_repo_and_persists_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="finance-tool"))
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/materialize",
            method="POST",
        )

        response = await endpoint(
            draft.id,
            MaterializeRequest(output_dir=str(tmp_path / "generated")),
        )
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["draft"]["status"] == "materialized"
        assert data["draft"]["materialize_status"] == "succeeded"
        assert data["draft"]["materialized_path"].endswith("generated/finance-tool")
        assert data["materialized"]["path"].endswith("generated/finance-tool")
        assert (tmp_path / "generated" / "finance-tool" / "pyproject.toml").exists()
        persisted = state.get_onboarding_draft(draft.id)
        assert persisted["materialize_status"] == "succeeded"
        assert persisted["materialized_path"].endswith("generated/finance-tool")

    @pytest.mark.asyncio
    async def test_push_draft_requires_materialized_repo(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/push",
            method="POST",
        )

        response = await endpoint(draft.id)
        data = json.loads(response.body)

        assert response.status_code == 409
        assert data["error"] == "Draft must be materialized before it can be pushed"

    @pytest.mark.asyncio
    async def test_push_draft_creates_and_pushes_github_repo(
        self, config, event_bus, state, tmp_path, monkeypatch
    ) -> None:
        repo_dir = tmp_path / "generated" / "finance-tool"
        repo_dir.mkdir(parents=True)
        (repo_dir / "README.md").write_text("# finance-tool\n")
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="finance-tool")),
            status="materialized",
            materialize_status="succeeded",
            materialized_path=str(repo_dir),
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        calls: list[tuple[str, ...]] = []

        class Proc:
            returncode = 0

            async def communicate(self):
                return b"", b""

            def kill(self) -> None:
                return None

        async def fake_exec(*cmd, **_kwargs):
            calls.append(tuple(cmd))
            return Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/push",
            method="POST",
        )

        response = await endpoint(draft.id)
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["draft"]["status"] == "pushed"
        assert data["draft"]["push_status"] == "succeeded"
        assert data["repo_url"] == "https://github.com/T-rav/finance-tool"
        assert (
            "gh",
            "repo",
            "create",
            "T-rav/finance-tool",
            "--private",
            "--description",
            "A repo for experimenting with observability workflows.",
        ) in calls
        assert ("git", "push", "-u", "origin", "main") in calls
        assert ("git", "push", "-u", "origin", "staging") in calls
        persisted = state.get_onboarding_draft(draft.id)
        assert persisted["repo_url"] == "https://github.com/T-rav/finance-tool"

    @pytest.mark.asyncio
    async def test_push_draft_records_cli_failure(
        self, config, event_bus, state, tmp_path, monkeypatch
    ) -> None:
        repo_dir = tmp_path / "generated" / "finance-tool"
        repo_dir.mkdir(parents=True)
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="finance-tool")),
            status="materialized",
            materialize_status="succeeded",
            materialized_path=str(repo_dir),
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))

        class Proc:
            returncode = 1

            async def communicate(self):
                return b"", b"gh auth required"

            def kill(self) -> None:
                return None

        async def fake_exec(*_cmd, **_kwargs):
            return Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/push",
            method="POST",
        )

        response = await endpoint(draft.id)
        data = json.loads(response.body)

        assert response.status_code == 502
        assert data["draft"]["status"] == "materialized"
        assert data["draft"]["push_status"] == "failed"
        assert "gh auth required" in data["draft"]["events"][-1]["message"]

    @pytest.mark.asyncio
    async def test_design_chat_persists_conversation_and_field_updates(
        self, config, event_bus, state, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("HYDRAFLOW_ONBOARDING_ANTHROPIC_API_KEY", raising=False)
        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/design/chat",
            method="POST",
        )

        response = await endpoint(
            draft.id,
            DesignChatRequest(
                message=(
                    "Build finance-tool as a public Python FastAPI React app "
                    "with Postgres, branch protection, deterministic tests, and 92% coverage."
                )
            ),
        )
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["draft"]["spec"]["name"] == "finance-tool"
        assert data["draft"]["spec"]["visibility"] == "public"
        assert data["draft"]["spec"]["coverage_floor"] == 92
        assert "FastAPI" in data["draft"]["spec"]["tech_stack"]
        assert "React" in data["draft"]["spec"]["tech_stack"]
        assert "branch-protection" in data["draft"]["spec"]["safety_guards"]
        assert data["draft"]["chat_messages"][-1]["role"] == "assistant"
        assert state.get_onboarding_draft(draft.id)["extracted_fields"]["name"] == (
            "finance-tool"
        )

    @pytest.mark.asyncio
    async def test_design_chat_falls_back_when_live_provider_fails(
        self, config, event_bus, state, tmp_path, monkeypatch
    ) -> None:
        class FailingProvider:
            async def chat(self, _draft, _message):
                raise DesignProviderError("rate limited")

        import dashboard_routes._onboarding_routes as onboarding_routes

        monkeypatch.setattr(
            onboarding_routes,
            "design_ai",
            DesignAIService(provider=FailingProvider()),
        )
        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/design/chat",
            method="POST",
        )

        response = await endpoint(
            draft.id,
            DesignChatRequest(message="Build finance-tool with FastAPI and no UI."),
        )
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["draft"]["spec"]["name"] == "finance-tool"
        assert data["draft"]["events"][-1]["message"] == (
            "design chat used form-fill fallback: rate limited"
        )

    @pytest.mark.asyncio
    async def test_anthropic_provider_returns_structured_turn(
        self, monkeypatch
    ) -> None:
        requests: list[dict[str, object]] = []

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "reply": "I updated the backend and UI.",
                                    "field_updates": {
                                        "name": "finance-tool",
                                        "tech_stack": ["python", "FastAPI", "React"],
                                        "unknown": "ignored",
                                    },
                                    "clarification": None,
                                }
                            ),
                        }
                    ]
                }

        class Client:
            def __init__(self, **_kwargs) -> None:
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> None:
                return None

            async def post(self, url, **kwargs):
                requests.append({"url": url, **kwargs})
                return Response()

        import onboarding.design_ai as design_ai_module

        monkeypatch.setattr(design_ai_module.httpx, "AsyncClient", Client)
        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        provider = AnthropicDesignProvider(api_key="sk-test", model="claude-test")

        turn = await provider.chat(draft, "Use FastAPI and React.")

        assert turn.source == "claude"
        assert turn.reply == "I updated the backend and UI."
        assert turn.field_updates == {
            "name": "finance-tool",
            "tech_stack": ["python", "FastAPI", "React"],
        }
        assert requests[0]["url"] == "https://api.anthropic.com/v1/messages"
        assert requests[0]["headers"]["x-api-key"] == "sk-test"

    @pytest.mark.asyncio
    async def test_design_service_uses_live_provider_when_configured(self) -> None:
        class Provider:
            async def chat(self, _draft, _message):
                return DesignTurn(
                    reply="Claude reply",
                    field_updates={"name": "finance-tool"},
                    source="claude",
                )

        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        service = DesignAIService(provider=Provider())

        turn = await service.chat(draft, "Build finance-tool.")

        assert turn.source == "claude"
        assert turn.field_updates == {"name": "finance-tool"}

    @pytest.mark.asyncio
    async def test_design_spec_and_plan_are_persisted(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(
                _spec_payload(
                    name="finance-tool",
                    tech_stack=["python", "FastAPI", "React"],
                    safety_guards=["branch-protection", "decimal-purity"],
                )
            )
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        spec_endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/design/spec",
            method="POST",
        )
        plan_endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/design/plan",
            method="POST",
        )

        spec_response = await spec_endpoint(
            draft.id, DesignRevisionRequest(note="include v1 boundaries")
        )
        plan_response = await plan_endpoint(draft.id, DesignRevisionRequest())
        spec_data = json.loads(spec_response.body)
        plan_data = json.loads(plan_response.body)

        assert spec_response.status_code == 200
        assert "10-file Invariant Kernel" in spec_data["spec_draft"]
        assert "V1 IN" in spec_data["spec_draft"]
        assert plan_response.status_code == 200
        assert len(plan_data["plan_draft"]) >= 10
        assert any("UI scaffold" in task for task in plan_data["plan_draft"])
        assert any("decimal-purity" in task for task in plan_data["plan_draft"])
        persisted = state.get_onboarding_draft(draft.id)
        assert persisted["spec_draft"] == spec_data["spec_draft"]
        assert persisted["plan_draft"] == plan_data["plan_draft"]

    @pytest.mark.asyncio
    async def test_continue_plan_drafts_next_plan_and_files_find_issues(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(
                _spec_payload(
                    name="finance-tool",
                    tech_stack=["python", "FastAPI", "React"],
                    safety_guards=["branch-protection"],
                )
            )
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(side_effect=list(range(501, 520)))  # type: ignore[method-assign]
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/continue-plan",
            method="POST",
        )

        response = await endpoint(
            draft.id,
            ContinuePlanRequest(note="prioritize factory registry handoff"),
        )
        data = json.loads(response.body)

        assert response.status_code == 200
        assert data["plan"] == "Plan 02"
        assert len(data["created_issues"]) == len(data["plan_draft"])
        assert data["created_issues"][0]["number"] == 501
        assert pr_mgr.create_issue.await_count == len(data["plan_draft"])
        first_call = pr_mgr.create_issue.await_args_list[0].kwargs
        assert first_call["title"].startswith("[Plan 02]")
        assert first_call["labels"] == ["hydraflow-find"]
        assert "Target repo: T-rav/finance-tool" in first_call["body"]
        persisted = state.get_onboarding_draft(draft.id)
        assert persisted["plan_draft"] == data["plan_draft"]
        assert persisted["events"][-1]["message"].startswith("Plan 02 filed")

    @pytest.mark.asyncio
    async def test_materialize_draft_records_failure_for_existing_target(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(
            spec=BootstrapSpec.model_validate(_spec_payload(name="finance-tool"))
        )
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        target = tmp_path / "generated" / "finance-tool"
        target.mkdir(parents=True)
        (target / "README.md").write_text("existing")
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/materialize",
            method="POST",
        )

        response = await endpoint(
            draft.id,
            MaterializeRequest(output_dir=str(tmp_path / "generated")),
        )
        data = json.loads(response.body)

        assert response.status_code == 409
        assert data["draft"]["status"] == "error"
        assert data["draft"]["materialize_status"] == "failed"
        assert data["error"] == "Draft could not be materialized"
        assert "already exists" in data["draft"]["events"][-1]["message"]

    @pytest.mark.asyncio
    async def test_materialize_draft_rejects_disallowed_output_dir(
        self, config, event_bus, state, tmp_path
    ) -> None:
        draft = BootstrapDraft(spec=BootstrapSpec.model_validate(_spec_payload()))
        state.set_onboarding_draft(draft.id, draft.model_dump(mode="json"))
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(
            router,
            "/api/onboarding/drafts/{draft_id}/materialize",
            method="POST",
        )

        response = await endpoint(draft.id, MaterializeRequest(output_dir="/etc"))

        assert response.status_code == 400
        assert "output_dir" in json.loads(response.body)["error"]
