"""Tests for the headless onboarding draft API."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from onboarding.models import BootstrapDraft, BootstrapSpec
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
