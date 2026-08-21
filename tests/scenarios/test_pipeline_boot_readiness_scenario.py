"""Scenario: the single-truth invariant across a simulated restart (#11279).

Right after a factory restart, ``IssueStore._queues`` is populated with every
stage key mapped to an empty deque before the first background ``refresh()``
runs. A client's WS-reconnect-triggered ``GET /api/pipeline`` poll can land
during that boot window, and the response used to be indistinguishable in
shape from a genuinely empty pipeline — so the frontend's authoritative
reconcile wiped the rail even though GitHub's labels (the actual source of
truth, ADR-0002) never changed.

This scenario drives the real ``GET /api/pipeline`` route handler — the same
one production traffic hits — across that boot window and asserts the
single-truth invariant explicitly requested by the issue: once the store
reports ready, the rail matches the label truth exactly; before that, the
route never claims an empty rail is authoritative.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mockworld.fakes.fake_issue_store import FakeIssueStore
from tests.helpers import find_endpoint, make_dashboard_router

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_rail_converges_to_label_truth_after_simulated_restart(
    mock_world, config, event_bus, state, tmp_path
) -> None:
    mock_world.github.add_issue(1, "find me", "body", labels=["hydraflow-find"])
    mock_world.github.add_issue(2, "plan me", "body", labels=["hydraflow-plan"])
    store = FakeIssueStore(github=mock_world.github, event_bus=event_bus)

    # Simulate the post-restart boot window: labels are already the ones
    # seeded above (GitHub's state never resets on a HydraFlow restart), but
    # this process hasn't completed its first refresh cycle yet.
    store._has_completed_initial_refresh = False  # noqa: SLF001

    orch = SimpleNamespace(running=True, pipeline_enabled=True, issue_store=store)
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: orch
    )
    endpoint = find_endpoint(router, "/api/pipeline")
    assert endpoint is not None

    # A WS-reconnect poll landing mid-boot must not claim the rail is empty.
    boot_payload = json.loads((await endpoint(repo=None)).body)
    assert boot_payload["ready"] is False
    assert boot_payload["stages"] == {}

    # The restart's initial refresh completes.
    await store.refresh()

    # A subsequent poll now converges to the label truth exactly (rail ==
    # labels) — the single-truth invariant the issue asked for.
    settled_payload = json.loads((await endpoint(repo=None)).body)
    assert settled_payload["ready"] is True
    assert [i["issue_number"] for i in settled_payload["stages"]["triage"]] == [1]
    assert [i["issue_number"] for i in settled_payload["stages"]["plan"]] == [2]
