"""s84 - SampledAuditLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``SampledAuditLoop`` and an
idle cycle (no seeded commit-range state — the cursor primes on the first tick)
completes without error, proving the loop is registered, wired through all the
checkpoints, and heartbeating in the real Docker stack (#10370: the silent-
escape estimator — sampled adversarial re-audit).

The sampling / stratification / Shewhart rate governance / audit recording /
upheld→escape-ledger cross-link behavior itself is covered by the unit tests
(``tests/test_audit_engine.py``, ``tests/test_sampled_audit_loop.py``) and the
Tier-1 MockWorld scenario (``tests/scenarios/test_sampled_audit_scenario.py``),
which drives a real tiny git repo + an INJECTED fake auditor end-to-end. That
isn't yet expressible via ``MockWorldSeed`` (no seeded-git-history field), and
the adversarial re-audit spawn is pinned OFF on the air-gapped sandbox network
(the ``sampled_audit_loop`` config_disable seam in ``mockworld.sandbox_main``),
so this Tier-2 layer stays scoped to proving the loop actually runs inside the
container — matching the idle-poll pattern used by s83 for the escape ledger.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s84_sampled_audit_idle_poll"
DESCRIPTION = "SampledAuditLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["sampled_audit"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by SampledAuditLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "sampled_audit"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "sampled_audit"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one sampled_audit worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
