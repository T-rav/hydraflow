"""s51 — ConvergenceOscillationLoop: snapshot-path cross-boundary oscillation escalation.

This scenario exercises the ``ConvergenceOscillationLoop`` caretaker (ADR-0029)
end-to-end inside the docker sandbox.  It drives issue #1 through three pipeline
phases so that the ledger's snapshot state satisfies the oscillation detector:

  triage.last_verdict  == "LOOP_BACK"   (routed to discover)
  plan.last_verdict    == "LOOP_BACK"   (plan fails, issue stays on hydraflow-plan)

Two distinct boundary stages with ``last_verdict == "LOOP_BACK"`` meets the
default ``min_loopback_stages=2`` threshold, so ``detect_cross_boundary_oscillation``
returns True on the snapshot check (without needing temporal outer-oscillation).

----------------------------------------------------------------------
WHY THE SNAPSHOT PATH (not the temporal/lap path)
----------------------------------------------------------------------
The temporal outer-oscillation path (``detect_outer_oscillation``) fires when
``>= window`` consecutive review laps have identical finding signatures.  That
requires at least ``window`` (default 2) full review laps, each closed via
``ledger.mark_lap()``.  Reaching two laps involves: implement → review reject →
loop-back → implement again → review reject again — seven or more phases.
Driving that reliably without racing the lap-cap (``max_convergence_laps``) that
triggers a separate HITL escalation before the oscillation detector fires would
require carefully coordinated timing or script entries.

The snapshot path fires much earlier: as soon as ``>= min_loopback_stages``
(default 2) distinct boundary stages simultaneously hold ``last_verdict ==
"LOOP_BACK"``.  It does not depend on lap count, review verdicts, or temporal
history — only the current ledger snapshot.  We therefore drive the issue into
the snapshot state and let the caretaker's 60-second sandbox tick detect it.

----------------------------------------------------------------------
PIPELINE ROUTE THAT PRODUCES BOTH LOOP_BACKs SIMULTANEOUSLY
----------------------------------------------------------------------
1. Issue starts with ``hydraflow-find`` → triage picks it up.
2. Triage scripts ``needs_discovery=True`` → routing outcome ``"discover"`` →
   ``_TRIAGE_VERDICT_MAP["discover"] == "LOOP_BACK"`` recorded for stage
   ``"triage"``.  Issue gets ``hydraflow-discover`` label.
3. DiscoverPhase runs with no real runner (sandbox) → stub brief → routes
   issue to ``hydraflow-shape``.
4. ShapePhase runs with a shape runner (FakeSubprocessRunner, success) and
   the ExpertCouncil wired up via ``expert_council._mockworld_fake_llm``.
   ``phase_scripts={"shape_council": {1: {1: "consensus"}}}`` returns
   ``"consensus"`` for round 1 → council auto-selects Direction A → shape
   records ``ADVANCE`` and routes issue to ``hydraflow-plan``.
5. Plan script: ``{"success": False}`` → planner returns failure with no plan
   body and ``retry_attempted=False`` → plan falls into the ``ts_status =
   "failed"`` branch (PlanPhase._plan_one lines 1363-1368).  This branch SKIPS
   the label swap — issue STAYS on ``hydraflow-plan`` — and records
   ``_PLAN_VERDICT_MAP["failed"] == "LOOP_BACK"`` for stage ``"plan"``.
6. FakeLLM's ``_last_scripted`` repeat-semantics: once the deque is empty the
   runner keeps returning the same failure, so the plan loop continuously
   re-attempts and re-records LOOP_BACK.  The issue does not advance.
7. At ~60 seconds the ``ConvergenceOscillationLoop`` ticks (sandbox
   ``interval_cb`` overrides all loop intervals to 60 s regardless of config).
   It finds the ledger for issue #1 with:
     ``stage_state["triage"].last_verdict == "LOOP_BACK"``
     ``stage_state["plan"].last_verdict  == "LOOP_BACK"``
   ``detect_cross_boundary_oscillation`` returns True (2 >= min_loopback_stages=2).
8. The loop calls ``prs.create_issue(title, body, ["hitl-escalation",
   "convergence-oscillation"])`` (FakeGitHub supports this) and calls
   ``state.mark_oscillation_escalated(1)`` → ``ledger.oscillation_escalated = True``.
9. ``/api/state`` reflects the updated ledger → ``assert_outcome`` predicate
   fires.

----------------------------------------------------------------------
OSCILLATION LOOP INTERVAL IN SANDBOX
----------------------------------------------------------------------
``HYDRAFLOW_CONVERGENCE_OSCILLATION_INTERVAL: "5"`` is set in
docker-compose.sandbox.yml as a signal of intent (short interval for testing).
However, the pydantic field enforces ``ge=300`` (5 minutes minimum); the
``_apply_env_overrides`` function raises ``ValueError`` which is suppressed by
``contextlib.suppress(ValueError)`` — the config field remains at its default of
3600.  This is harmless: the sandbox bootstraps all caretaker loops with
``WorkerRegistryCallbacks(get_interval=lambda *_a, **_kw: 60)``, which wires as
``LoopDeps.interval_cb`` and takes precedence over ``_get_default_interval()`` in
``BaseBackgroundLoop._get_interval()``.  The effective interval is therefore
60 seconds in every sandbox run, independent of the config field.  The assertion
timeout (120 s) comfortably accommodates one full tick margin.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s51_convergence_oscillation"
DESCRIPTION = (
    "ConvergenceOscillationLoop: triage routes to discover (LOOP_BACK) + plan "
    "fails (LOOP_BACK) → snapshot oscillation detected → ledger escalated."
)


def seed() -> MockWorldSeed:
    """Build the seed that drives the cross-boundary oscillation scenario.

    Issue #1 starts on ``hydraflow-find`` so triage picks it up.  The triage
    script produces ``needs_discovery=True`` (one scripted entry; FakeLLM
    repeats the last entry thereafter, but triage only runs once per label
    cycle).  The shape council is scripted to consensus on round 1 so shape
    immediately routes to plan.  The plan script returns a single failure which
    FakeLLM then repeats indefinitely, keeping the issue stuck in the
    ``plan-LOOP_BACK`` state until the oscillation loop escalates it.
    """
    return MockWorldSeed(
        # Only the convergence-oscillation caretaker is enabled; pipeline phase
        # orchestrators (triage/shape/plan) run regardless (loops_enabled gates
        # caretakers only, per sandbox_main._build_caretaker_enabled_cb). This
        # also makes the Tier-1 in-process parity test use the run_with_loops
        # path instead of single-shot run_pipeline (which cannot reproduce the
        # multi-cycle triage+plan LOOP_BACK oscillation).
        loops_enabled=["convergence_oscillation"],
        issues=[
            {
                "number": 1,
                "title": "Investigate recurring churn in auth module",
                "body": (
                    "The auth module changes have been cycling through triage and "
                    "planning without converging. Need deep product discovery first."
                ),
                "labels": ["hydraflow-find"],
            }
        ],
        scripts={
            # Triage script: needs_discovery=True routes the issue to
            # hydraflow-discover and records triage LOOP_BACK in the ledger.
            # FakeLLM pops this entry, then repeats it (last-scripted semantics)
            # but triage only runs once per find-label cycle so only one triage
            # verdict lands.
            "triage": {1: [{"needs_discovery": True}]},
            # Plan script: success=False (no plan body) causes PlanPhase to set
            # ts_status="failed", skip the label swap (issue stays on
            # hydraflow-plan), and record plan LOOP_BACK in the ledger.
            # FakeLLM repeats this failure after the deque empties, so the plan
            # loop continuously re-fails and re-records LOOP_BACK — the issue
            # remains stuck until the oscillation loop escalates it.
            "plan": {1: [{"success": False}]},
        },
        # Shape council scripting: wired via expert_council._mockworld_fake_llm
        # in sandbox_main.py. Round 1 = "consensus" → ExpertCouncil.vote
        # returns a CouncilResult with all three experts voting Direction A →
        # has_consensus=True → ShapePhase._run_council_vote returns 1 →
        # shape records ADVANCE and routes issue to hydraflow-plan.
        phase_scripts={
            "shape_council": {1: {1: "consensus"}},
        },
        # cycles_to_run is used by the Tier-1 (in-process) parity test
        # (test_sandbox_parity.py). The Tier-2 docker sandbox runs
        # indefinitely until assertions pass. 16 cycles gives the parity
        # test enough iterations for: find → triage → discover → shape →
        # plan-fail × N, which is more than sufficient for the ledger to
        # reach the oscillation state. In docker the assert_outcome timeout
        # (120 s) covers the 60-second caretaker tick with margin.
        cycles_to_run=16,
    )


async def assert_outcome(api, page) -> None:
    """Assert that ConvergenceOscillationLoop escalated the stuck issue.

    Primary assertion: ``/api/state`` shows ``convergence_ledgers`` entry
    for issue #1 with ``oscillation_escalated == True``.  This is the direct
    proof that the real caretaker loop, running inside the real docker
    orchestrator, detected the cross-boundary oscillation state and escalated.

    The assertion polls with a generous 120-second timeout so the 60-second
    caretaker tick (sandbox interval_cb override) has time to fire and the
    ledger write to propagate through the StateTracker before the deadline.
    """
    _ = page  # UI interaction not needed for this caretaker assertion

    def _oscillation_escalated(payload: object) -> bool:
        """Return True when issue #1's ledger shows oscillation_escalated=True."""
        if not isinstance(payload, dict):
            return False
        ledgers = payload.get("convergence_ledgers")
        if not isinstance(ledgers, dict):
            return False
        # The ledger key is StateTracker._key(1) == "1" in the single-repo
        # sandbox. Accept any entry whose issue_number field == 1 in case the
        # key format changes (mirrors s50's defensive iteration pattern).
        for entry in ledgers.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("issue_number") != 1:
                continue
            if entry.get("oscillation_escalated") is True:
                return True
        return False

    await api.wait_until(
        "/api/state",
        _oscillation_escalated,
        timeout=120.0,
    )
