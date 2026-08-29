"""s94 — the onboarding path writes ``charter.yaml`` (#11748).

Docker-tier proof of the two halves of the charter contract, in the real
stack:

1. **The onboarding path writes the charter.** ``POST /api/onboarding/drafts``
   then ``POST .../materialize`` runs the real templating service inside the
   container and must report ``charter.yaml`` among the files it wrote. This
   is the layer that catches wiring that unit tests cannot see — a charter
   renderer that imports cleanly in pytest but not from the dashboard
   process, or a file dropped from ``_render_files`` by a bad merge.
2. **The renamed caretaker is still wired.** ``CharterDriftCaretakerLoop``
   (worker ``charter_drift_caretaker``, formerly ``rails_drift_caretaker``)
   emits a BACKGROUND_WORKER_STATUS event, proving the loop survived the
   rename across the registry, service-registry and orchestrator wiring
   sites.

The materialized repo lands under the container's temp directory — the only
writable root ``_allowed_output_dir`` permits besides ``$HOME`` — and the
name carries a random suffix so a re-run in a warm container never trips the
"target directory already exists" guard.
"""

from __future__ import annotations

import uuid

from mockworld.seed import MockWorldSeed

NAME = "s94_onboarding_writes_charter"
DESCRIPTION = (
    "Onboarding materialize writes charter.yaml, and the renamed "
    "charter_drift_caretaker loop still ticks."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["charter_drift_caretaker"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Materialize a draft through the real API; assert the charter is written."""
    repo_name = f"charter-probe-{uuid.uuid4().hex[:8]}"
    draft = await api.post(
        "/api/onboarding/drafts",
        json={
            "name": repo_name,
            "description": "A probe repo used to prove onboarding writes a charter.",
            "owner": "T-rav",
            "visibility": "private",
            "tech_stack": ["python"],
            "coverage_floor": 85,
        },
    )
    draft_id = draft.get("id")
    assert draft_id, f"draft creation returned no id: {draft!r}"

    result = await api.post(
        f"/api/onboarding/drafts/{draft_id}/materialize",
        json={"output_dir": "/tmp/hydraflow-charter-e2e"},
    )
    written = {item["path"] for item in result.get("materialized", {}).get("files", [])}
    assert "charter.yaml" in written, (
        "onboarding materialize did not write charter.yaml; "
        f"it wrote {sorted(written)!r}"
    )

    def _charter_loop_ticked(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and (e.get("data") or {}).get("worker") == "charter_drift_caretaker"
            for e in events
        )

    events = await api.wait_until("/api/events", _charter_loop_ticked, timeout=60.0)
    ticks = [
        e
        for e in events
        if e.get("type") == "background_worker_status"
        and (e.get("data") or {}).get("worker") == "charter_drift_caretaker"
    ]
    assert ticks, f"charter_drift_caretaker never reported status: {events!r}"
