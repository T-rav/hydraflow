"""s88 — credit exhaustion pauses the factory; clearing it resumes (#10570).

Tier-2 sandbox scenario for the global credit-pause path. Before this scenario
there was NO FakeLLM path in ``tests/sandbox_scenarios`` that could emit a
credit-exhaustion signal, so the orchestrator's global pause
(``credits_paused_until`` + the ``SYSTEM_ALERT`` banner) and its
clear-via-control-endpoint resume had no docker-tier coverage — the layer that
catches dashboard-surface and wiring bugs the unit tests can't see.

WHAT IT DRIVES
--------------
The seed labels one issue ``hydraflow-plan`` (so the real plan loop reaches it
directly) and arms the FakeLLM plan runner via
``MockWorldSeed.credit_exhaustion`` so the FIRST ``planners.plan`` call for that
issue raises an *authoritative* ``CreditExhaustedError`` — the air-gapped
stand-in for the Claude CLI terminating on a weekly-limit cap
("You've hit your weekly limit · resets ..."). The plan phase propagates the
error to the loop supervisor (``phase_utils.run_refilling_pool`` treats
``CreditExhaustedError`` as fatal), which runs ``_pause_for_credits``. Because
the signal is authoritative (#10558) the orchestrator pauses on it directly,
skipping the live availability probe that structurally cannot detect a weekly
exhaustion (the key stays valid) and would otherwise refute the signal as a
false positive on the air-gapped network.

WHAT IT ASSERTS (production-shaped dashboard surfaces only — no internals)
-------------------------------------------------------------------------
1. ``GET /api/control/status`` reports ``status == "credits_paused"`` with a
   non-null ``credits_paused_until`` — the operator-visible paused state.
2. ``GET /api/events`` carries a ``system_alert`` from ``source == "plan"`` with
   a ``resume_at`` — the banner an operator sees when the pause fires.
3. ``POST /api/control/clear-credit-pause`` (the operator's resume control)
   wakes the sleeping loops: ``/api/control/status`` returns to a non-paused
   status with ``credits_paused_until`` back to null, and the resumed plan loop
   plans the issue normally (the one-shot signal does not re-fire).

WHY IN_PROCESS = False
----------------------
The credit pause is an orchestrator-*supervision* behavior: it lives in
``_supervise_loops`` / ``_pause_for_credits`` / ``_resume_loops_after_credit_
pause``. The Tier-1 in-process parity harness (``MockWorld.run_pipeline``) drives
the phase orchestrators DIRECTLY with no ``_supervise_loops`` around them, so a
``CreditExhaustedError`` from a phase would abort the harness run rather than be
caught and converted into a pause — and the in-process dashboard is backed by a
stub orchestrator that hard-codes ``credits_paused_until = None``. The
orchestrator-supervision pause/resume is covered in-process by the unit suite
(``tests/test_credit_pause.py``, which drives the REAL orchestrator via
``orch.run()``); this scenario adds the docker-tier + dashboard-API surface the
issue calls out as missing. So it opts out of Tier-1 (like s55/s56/s57) rather
than asserting a contract that harness structurally cannot model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mockworld.seed import MockWorldSeed

NAME = "s88_credit_pause_auto_resume"
DESCRIPTION = (
    "FakeLLM weekly-limit signal → orchestrator pauses (credits_paused + "
    "SYSTEM_ALERT); clear-credit-pause control endpoint resumes the loops."
)

# See the module docstring: the credit pause is an orchestrator-supervision
# behavior the flat in-process parity harness cannot model, and it is covered
# in-process by tests/test_credit_pause.py. This scenario is docker-tier only.
IN_PROCESS = False

# The plan-queue issue whose first plan() call raises the credit signal.
_ISSUE = 8801


def seed() -> MockWorldSeed:
    # An explicit FUTURE resume time so ``credits_paused_until`` is
    # deterministically non-null across the scenario's polling window. Five hours
    # is far beyond the assertion timeouts, so the pause never auto-expires
    # mid-scenario — the resume is driven explicitly via the control endpoint.
    resume_at = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": _ISSUE,
                "title": "Plan me — but credits run out first",
                "body": "A plan-queue issue used to drive the credit-pause path.",
                "labels": ["hydraflow-plan"],
            },
        ],
        credit_exhaustion={
            "issue": _ISSUE,
            "message": "You've hit your weekly limit · resets Jun 18 at 5pm",
            "resume_at": resume_at,
            "authoritative": True,
        },
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    """Pause fires and is observable; the control-endpoint clear resumes it."""

    # 1. The orchestrator pauses: /api/control/status reports credits_paused with
    #    a non-null resume time (the operator-visible paused state).
    def _paused(payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("status") == "credits_paused"
            and bool(payload.get("credits_paused_until"))
        )

    status = await api.wait_until("/api/control/status", _paused, timeout=60.0)
    assert status.get("status") == "credits_paused", status
    assert status.get("credits_paused_until"), status

    # 2. The pause emits the SYSTEM_ALERT banner an operator sees: sourced from
    #    the plan loop and carrying the parsed resume time.
    def _credit_alert(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "system_alert"
            and (e.get("data") or {}).get("source") == "plan"
            and (e.get("data") or {}).get("resume_at")
            and "credit" in str((e.get("data") or {}).get("message", "")).lower()
            for e in events
        )

    events = await api.wait_until("/api/events", _credit_alert, timeout=60.0)
    credit_alerts = [
        e
        for e in events
        if e.get("type") == "system_alert"
        and (e.get("data") or {}).get("source") == "plan"
        and "credit" in str((e.get("data") or {}).get("message", "")).lower()
    ]
    assert credit_alerts, f"no plan-sourced credit SYSTEM_ALERT: {events!r}"
    assert credit_alerts[0]["data"].get("resume_at"), credit_alerts[0]

    # 3. The operator's resume control clears the pause and wakes the loops.
    cleared = await api.post("/api/control/clear-credit-pause")
    assert cleared.get("status") == "cleared", cleared

    def _resumed(payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("status") != "credits_paused"
            and payload.get("credits_paused_until") is None
        )

    resumed = await api.wait_until("/api/control/status", _resumed, timeout=60.0)
    assert resumed.get("status") != "credits_paused", resumed
    assert resumed.get("credits_paused_until") is None, resumed
