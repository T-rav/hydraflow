"""Regression: ``/api/state`` must encode timestamps nested in state models."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pending_concerns import AdversarialState, Concern
from tests.helpers import find_endpoint, make_dashboard_router


@pytest.mark.asyncio
async def test_api_state_serializes_nested_datetime_fields(
    config, event_bus, state, tmp_path
) -> None:
    raised_at = datetime(2026, 8, 20, 23, 35, tzinfo=UTC)
    state.set_adversarial_state(
        42,
        AdversarialState(
            phase="plan",
            pending_concerns=[
                Concern(
                    id="concern-1",
                    raised_in_phase="plan",
                    raised_in_stage="spec_judge",
                    severity="HIGH",
                    concern="The plan needs a concrete rollback path.",
                    raised_at=raised_at,
                    must_address_by="implement",
                )
            ],
        ),
    )
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/api/state")

    response = await endpoint()
    data = json.loads(response.body)

    assert response.status_code == 200
    assert (
        data["adversarial_states"]["42"]["pending_concerns"][0]["raised_at"]
        == raised_at.isoformat()
    )
