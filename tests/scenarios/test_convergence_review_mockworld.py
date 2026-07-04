"""MockWorld scenarios — convergence gate at the review boundary.

Verifies three behaviours of the unconditional convergence gate:

1. ``test_loop_back_records_lap`` — a PR that fails review on pass 1
   (REQUEST_CHANGES) loops back to the ready queue; the ledger records the
   lap.  The test confirms the ledger is populated by the real gate logic
   running inside MockWorld.  Full converge-after-loopback (two pipeline
   passes) is deferred: ``run_pipeline`` is single-shot by design, and the
   ``run_with_loops`` catalog does not expose implement/review pipeline phases.

2. ``test_oscillation_escalates`` — a single REQUEST_CHANGES result pushes the
   issue over the outer lap budget (``max_convergence_laps=1``), causing
   escalation to HITL.  After escalation ``reset_outer_laps`` resets
   ``laps=0`` and ``lap_signatures=[]`` so a human-fixed re-queued issue
   starts with a fresh outer budget (the "fresh-budget-after-HITL" contract
   introduced in commit #9693).  ``stage_state``, ``blast_radius``,
   ``converged``, and ``oscillation_escalated`` are preserved.

3. ``test_approve_converges`` — a PR with an APPROVE review verdict and a
   scripted post-verify advisor APPROVE passes the gated path end-to-end:
   ``_convergence_decision(review_approved=True)`` runs the lens judge once
   (low blast radius = 1 pass), records ``last_verdict=="ADVANCE"``, flips
   ``ledger.converged`` to True, and merges the PR.  After the merge
   ``PostMergeHandler.handle_approved`` clears the ledger via
   ``clear_convergence_ledger`` (commit #9693).  The test captures the
   pre-clear ledger state through a monkeypatch observer so the converged=True
   proof survives the clear.

These are **integration-level** scenarios: the real ``ReviewPhase._handle_approved_review_gated``
/ ``_handle_rejected_review_gated`` and ``ConvergenceLedger`` run; nothing is
hand-populated in the ledger.
"""

from __future__ import annotations

import json

import pytest

from models import ReviewVerdict
from tests.conftest import ReviewResultFactory
from tests.scenarios.builders import IssueBuilder
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_world_with_gate(tmp_path, *, max_convergence_laps: int = 3) -> MockWorld:
    """Return a fresh MockWorld for convergence-gate scenarios.

    The gate is always-on (unconditional since the legacy fork was removed).
    We pass a config built before constructing MockWorld so that
    ``ReviewPhase`` (wired in ``PipelineHarness.__init__``) picks up
    ``max_convergence_laps`` at construction time.
    """
    from tests.helpers import ConfigFactory

    cfg = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        max_workers=1,
        max_planners=1,
        max_reviewers=1,
        visual_validation_enabled=False,
        max_ci_fix_attempts=0,
    )
    cfg.max_convergence_laps = max_convergence_laps
    return MockWorld(tmp_path, config=cfg)


# ---------------------------------------------------------------------------
# Probe / verification (inline — not a standalone test class)
# ---------------------------------------------------------------------------
# The probe is embedded in test_loop_back_records_lap:  if the ledger is
# None after a scripted REQUEST_CHANGES with the gate ON, the test will fail
# with a clear assertion message rather than a vacuous pass.


# ---------------------------------------------------------------------------
# Scenario 1 — loop-back records one lap; issue stays un-merged
# ---------------------------------------------------------------------------


class TestLoopBackRecordsLap:
    """Gate ON: one REQUEST_CHANGES → loop-back, ledger records the lap.

    The single ``run_pipeline`` call delivers the scripted REQUEST_CHANGES
    verdict.  ``_handle_rejected_review_gated`` runs, records one lap in the
    ledger, and re-queues the issue back to ``ready``.  The test confirms:

    - The ledger is created and ``laps == 1`` (one reject lap closed).
    - ``ledger.converged`` is False (LOOP_BACK, not APPROVE).
    - The issue is NOT merged in this pipeline pass (it was re-queued).
    - ``final_stage`` is ``"review"`` (the reject result is the last record).

    Note: converge-after-loopback (two passes ending in APPROVE) is deferred.
    ``run_pipeline`` is single-shot by design; a two-pass scenario requires
    running a second fresh ``MockWorld`` with the re-queued issue, which falls
    outside the scope of this unit-level scenario.
    """

    async def test_loop_back_records_lap(self, tmp_path) -> None:
        world = _make_world_with_gate(tmp_path)

        IssueBuilder().numbered(1).titled("Fix bug").bodied("A bug to fix").at(world)

        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world.set_phase_results("review", 1, [reject])

        result = await world.run_pipeline()

        # --- probe: confirm the real gate ran and populated the ledger ---
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated REQUEST_CHANGES — "
            "the real _handle_rejected_review_gated did not run through MockWorld. "
            "BLOCKED: the gate is not exercised at this injection level."
        )

        # --- main assertions ---
        # One reject lap was closed by _convergence_decision → ledger.mark_lap().
        assert ledger.laps == 1, (
            f"Expected laps==1 after one REQUEST_CHANGES; got {ledger.laps}"
        )
        # The gate decision for a reject is LOOP_BACK, so converged stays False.
        assert ledger.converged is False

        outcome = result.issue(1)
        # The issue was re-queued (loop-back), not merged.
        assert outcome.merged is False
        assert outcome.review_result is not None
        assert outcome.review_result.verdict == ReviewVerdict.REQUEST_CHANGES
        # Pipeline routing: the reject result was the last record in this pass.
        assert outcome.final_stage == "review"


# ---------------------------------------------------------------------------
# Scenario 2 — repeated rejections exhaust the lap budget → HITL escalation
# ---------------------------------------------------------------------------


class TestOscillationEscalates:
    """Gate ON, lap budget exhausted → HITL escalation + fresh outer budget.

    We lower ``max_convergence_laps`` to 1 so that a single REQUEST_CHANGES
    lap immediately triggers the budget check inside ``_convergence_decision``:

        if LOOP_BACK and ledger.laps >= max_convergence_laps:
            result = escalate(...)

    After escalation ``_handle_rejected_review_gated`` calls
    ``_escalate_to_hitl``, which transitions the issue to the diagnose label
    (``hydraflow-diagnose``), not directly to ``hydraflow-hitl``).

    **Fresh-budget-after-HITL contract (commit #9693)**: after every
    gate-driven HITL escalation ``reset_outer_laps`` sets ``laps=0`` and
    clears ``lap_signatures`` so a human-fixed, re-queued issue starts with a
    fresh outer budget rather than immediately re-escalating.  ``stage_state``,
    ``blast_radius``, ``converged``, and ``oscillation_escalated`` are
    intentionally preserved (they carry diagnostic context the caretaker needs).

    The test asserts:

    - The escalation occurred: issue carries the diagnose label.
    - The issue is NOT merged.
    - Post-escalation ledger: ``laps == 0`` (reset), ``lap_signatures == []``
      (reset), ``stage_state["review"]`` still present and records the
      ESCALATE verdict (preserved).
    """

    async def test_oscillation_escalates(self, tmp_path) -> None:
        # Lower the budget so a single reject lap trips the cap.
        world = _make_world_with_gate(tmp_path, max_convergence_laps=1)

        IssueBuilder().numbered(1).titled("Looping bug").bodied(
            "Repeatedly fails review."
        ).at(world)

        reject = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            merged=False,
        )
        world.set_phase_results("review", 1, [reject])

        result = await world.run_pipeline()

        # --- probe: gate must have run and the ledger must still exist ---
        # (reset_outer_laps only resets counters; it does NOT delete the ledger)
        ledger = world.harness.state.get_convergence_ledger(1)
        assert ledger is not None, (
            "ConvergenceLedger is None after a gated REQUEST_CHANGES — "
            "the real gate did not run. BLOCKED."
        )

        # --- escalation confirmation: issue carries the diagnose label ---
        # Convergence escalation routes through the diagnostic loop first:
        # _escalate_to_hitl transitions to "diagnose" (hydraflow-diagnose),
        # not directly to hydraflow-hitl.
        outcome = result.issue(1)
        assert outcome.merged is False
        diagnose_label = world.harness.config.diagnose_label[0]
        issue_labels = outcome.labels
        assert diagnose_label in issue_labels, (
            f"Expected diagnose label {diagnose_label!r} in issue labels after "
            f"convergence escalation; got {issue_labels}"
        )

        # --- fresh-budget-after-HITL contract ---
        # reset_outer_laps was called after escalation: laps resets to 0 so the
        # human-fixed re-queued issue starts with a clean outer budget.
        assert ledger.laps == 0, (
            f"Expected laps==0 after HITL escalation (reset_outer_laps); got {ledger.laps}"
        )
        assert ledger.lap_signatures == [], (
            f"Expected lap_signatures==[] after reset_outer_laps; got {ledger.lap_signatures}"
        )

        # stage_state is preserved (diagnostic context survives the lap reset):
        # _convergence_decision recorded ESCALATE into stage_state["review"]
        # before reset_outer_laps was called.
        review_rec = ledger.stage_state.get("review")
        assert review_rec is not None, (
            "stage_state['review'] was wiped by reset_outer_laps — it should be preserved"
        )
        assert review_rec.last_verdict == "ESCALATE", (
            f"Expected stage_state['review'].last_verdict=='ESCALATE'; got {review_rec.last_verdict!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 3 — gated APPROVE path makes ledger.converged go True
# ---------------------------------------------------------------------------


class TestApproveConverges:
    """Gate ON: APPROVE review + scripted post-verify APPROVE → converged=True.

    This is the critical Phase-2 proof: the gated approve path runs
    ``_handle_approved_review_gated`` → ``_convergence_decision(review_approved=True)``
    → the HybridGate lens judge (one pass for low blast radius) → the scripted
    ``post_verify`` advisor → ADVANCE → ``ledger.converged = True`` → merge.

    Phase 1 could only exercise the reject path (REQUEST_CHANGES → LOOP_BACK).
    This scenario proves the ADVANCE branch is plumbed end-to-end in MockWorld:
    the real gate logic records ``last_verdict=="ADVANCE"``, calls
    ``recompute_converged``, and flips ``converged`` to True — all without
    hand-touching the ledger.

    **Clear-on-merge contract (commit #9693)**: after a successful merge
    ``PostMergeHandler.handle_approved`` calls ``clear_convergence_ledger`` so
    the post-run ledger is ``None``.  The ADVANCE/converged=True proof is
    captured via a monkeypatch observer that wraps ``clear_convergence_ledger``
    and snapshots the live ledger immediately before delegating to the real
    method (mirroring the ``test_ledger_ordering_retrospective_reads_before_clear``
    pattern in ``tests/test_post_merge_handler.py``).

    Post-verify advisor is scriptable in MockWorld via
    ``world._llm.script_advisor(issue, "post_verify", [payload])``.
    The ``_PostVerifyRunner`` inside ``ReviewPhase._build_post_verify_runner``
    detects the ``_mockworld_fake_llm`` sentinel on ``self._reviewers`` and
    pops the scripted result instead of dispatching a real Claude subprocess.
    For low blast radius, ``min_review_passes_for_blast_radius`` returns 1,
    so exactly one advisor pop is needed.

    Kill-switch env vars are set explicitly to guard against test-suite-wide
    overrides silently disabling the advisor and causing a vacuous pass.
    """

    async def test_approve_converges(self, tmp_path, monkeypatch) -> None:
        # Enable the advisor master + pr_review surface + post_verify role
        # kill-switches so _run_post_verify_for_surface does not short-circuit.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")

        world = _make_world_with_gate(tmp_path)

        IssueBuilder().numbered(1).titled("Add feature X").bodied(
            "Implement feature X as described in the spec."
        ).at(world)

        # Script the review executor to return APPROVE (the gate fires only on
        # APPROVE verdicts; REQUEST_CHANGES goes through the reject branch).
        approve_review = ReviewResultFactory.create(
            issue_number=1,
            verdict=ReviewVerdict.APPROVE,
            merged=False,  # MockWorld does not auto-merge; we assert outcome below.
        )
        world.set_phase_results("review", 1, [approve_review])

        # Script the post-verify advisor.  For blast_radius="low", the
        # HybridGate runs exactly one lens pass (min_review_passes_for_blast_radius
        # returns 1 for "low").  The lens for pass 0 is "correctness"
        # (_APPROVE_GATE_LENSES[0]), so PostVerifyAdvisor.run receives
        # lens="correctness" and passes role="post_verify:correctness" to the
        # runner.  The MockWorld _PostVerifyRunner routes by that compound role,
        # so we must script under "post_verify:correctness" — not "post_verify".
        advisor_payload = json.dumps(
            {
                "verdict": "APPROVE",
                "reasoning": "Diff matches intent; no concerns.",
                "disagreements": [],
                "suggested_fix_direction": None,
            }
        )
        world._llm.script_advisor(1, "post_verify:correctness", [advisor_payload])

        # --- pre-clear observer ---
        # After a successful merge clear_convergence_ledger wipes the ledger.
        # We capture a deep copy of the ledger BEFORE the clear so the
        # converged=True proof survives the post-merge clear.
        captured_pre_clear: list[object] = []
        state = world.harness.state
        _real_clear = state.clear_convergence_ledger

        def _capturing_clear(issue_number: int) -> None:
            snap = state.get_convergence_ledger(issue_number)
            if snap is not None:
                captured_pre_clear.append(snap)
            _real_clear(issue_number)

        monkeypatch.setattr(state, "clear_convergence_ledger", _capturing_clear)

        result = await world.run_pipeline()

        # --- probe: confirm the gate ran (observer must have captured something) ---
        assert captured_pre_clear, (
            "clear_convergence_ledger was never called with a live ledger — "
            "_handle_approved_review_gated did not run through MockWorld, or "
            "the merge did not complete. BLOCKED: approve-gate path not exercised."
        )

        # Inspect the pre-clear snapshot (the state the ledger held at merge time).
        pre_clear = captured_pre_clear[0]

        # Triage and plan stages ran before review; both should be present in the
        # pre-clear snapshot with last_verdict=="ADVANCE" (the pipeline advances
        # straight through on a happy-path scripted run).
        triage_record = pre_clear.stage_state.get("triage")
        assert triage_record is not None, (
            "No 'triage' stage record in the pre-clear ledger — "
            "triage_phase did not call record_stage_verdict for this issue."
        )
        assert triage_record.last_verdict == "ADVANCE", (
            f"Expected triage stage_state last_verdict=='ADVANCE'; "
            f"got {triage_record.last_verdict!r}"
        )

        plan_record = pre_clear.stage_state.get("plan")
        assert plan_record is not None, (
            "No 'plan' stage record in the pre-clear ledger — "
            "plan_phase did not call record_stage_verdict for this issue."
        )
        assert plan_record.last_verdict == "ADVANCE", (
            f"Expected plan stage_state last_verdict=='ADVANCE'; "
            f"got {plan_record.last_verdict!r}"
        )

        # The gate recorded ADVANCE for the review stage, which flips converged.
        review_record = pre_clear.stage_state.get("review")
        assert review_record is not None, (
            "No 'review' stage record in the pre-clear ledger after APPROVE path ran."
        )
        assert review_record.last_verdict == "ADVANCE", (
            f"Expected last_verdict=='ADVANCE' after gated APPROVE; "
            f"got {review_record.last_verdict!r}"
        )

        # converged must be True: recompute_converged(["review"]) was called
        # inside _convergence_decision after recording ADVANCE.
        assert pre_clear.converged is True, (
            f"Expected ledger.converged==True after ADVANCE decision (pre-clear snapshot); "
            f"got converged={pre_clear.converged!r}, laps={pre_clear.laps}"
        )

        # One lap was closed (mark_lap() is called in _convergence_decision).
        assert pre_clear.laps >= 1, (
            f"Expected ledger.laps >= 1 after gated approve path (pre-clear snapshot); "
            f"got {pre_clear.laps}"
        )

        # --- clear-on-merge contract ---
        # After handle_approved returns the ledger must be gone.
        assert state.get_convergence_ledger(1) is None, (
            "Expected convergence ledger to be cleared after successful merge "
            "(clear_convergence_ledger was called but ledger still exists)."
        )

        # The PR was merged: _handle_approved_review_gated calls
        # _handle_approved_merge when the gate returns ADVANCE.
        outcome = result.issue(1)
        assert outcome.merged is True, (
            "Expected issue #1 to be merged after gated ADVANCE; "
            f"got merged={outcome.merged!r}"
        )

        # The advisor was invoked exactly once (one lens pass, low blast radius).
        # Role is "post_verify:correctness" because lens="correctness" is the
        # first (and only) lens for blast_radius="low".
        assert world._llm.advisor_call_count_for("post_verify:correctness") == 1, (
            f"Expected exactly one post_verify:correctness advisor call; "
            f"got {world._llm.advisor_call_count_for('post_verify:correctness')}"
        )
