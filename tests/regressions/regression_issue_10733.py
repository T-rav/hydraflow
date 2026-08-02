"""Behavioral guard for the goal-supervisor operating contract (#10733).

The supervisor's safety is its PURE decision core, not the Fable prompt. This
exercises every rule of the operating contract end-to-end so a refactor can't
quietly change what it acts on vs escalates vs defers:

  1 classify (flake vs real)  2 tractable→nudge / blast→escalate
  3 cause-less → defer         4/5 give-up window → escalate
  7 known-incident-first       8 verify + re-arm (reconcile)

These are the load-bearing invariants — if any flips, the automated operator
either acts on something it shouldn't (over-reach) or sits on a real outage.
"""

from __future__ import annotations

from supervisor_observation import (
    BLAST_HIGH,
    CLASS_REAL,
    CLASS_TRANSIENT,
    GIVEUP_CAP,
    NUDGE_FLAG_BOOT_SHA_STALENESS,
    NUDGE_REARM_CREDIT_PROBE,
    NUDGE_RESTART_STALLED_LOOP,
    HealthSnapshot,
    ProposedAction,
    classify_action,
    decide,
    derive_incidents,
    reconcile_ledger,
)


# --- rule 7: known-incident knowledge first (deterministic remedies) ---------


def test_healthy_snapshot_yields_no_incidents_and_no_actions() -> None:
    snap = HealthSnapshot()
    assert derive_incidents(snap) == []
    d = decide(snapshot=snap, agent_actions=[], attempts={})
    assert not d.nudges and not d.escalations and not d.deferred


def test_stalled_loop_becomes_a_low_blast_restart_nudge() -> None:
    d = decide(
        snapshot=HealthSnapshot(stalled_loops=["staging_bisect"]),
        agent_actions=[],
        attempts={},
    )
    assert [n.kind for n in d.nudges] == [NUDGE_RESTART_STALLED_LOOP]
    assert d.nudges[0].target == "staging_bisect"
    assert d.nudges[0].diagnosis  # rule 3: a nudge always carries a cause
    assert not d.escalations


def test_error_loop_becomes_a_restart_nudge_and_dedups_with_stall() -> None:
    # Same loop both stalled AND error → one incident, not two.
    d = decide(
        snapshot=HealthSnapshot(stalled_loops=["repo_wiki"], error_loops=["repo_wiki"]),
        agent_actions=[],
        attempts={},
    )
    assert len(d.nudges) == 1
    assert d.nudges[0].target == "repo_wiki"


def test_credit_probe_overdue_becomes_a_rearm_nudge() -> None:
    d = decide(
        snapshot=HealthSnapshot(credit_probe_overdue=True), agent_actions=[], attempts={}
    )
    assert [n.kind for n in d.nudges] == [NUDGE_REARM_CREDIT_PROBE]


def test_boot_sha_stale_becomes_a_flag_nudge_naming_the_gap() -> None:
    d = decide(
        snapshot=HealthSnapshot(boot_sha_stale=True, commits_behind=7),
        agent_actions=[],
        attempts={},
    )
    assert [n.kind for n in d.nudges] == [NUDGE_FLAG_BOOT_SHA_STALENESS]
    assert "7" in d.nudges[0].diagnosis


# --- rule 2: blast-radius escalates, never self-nudges ----------------------


def test_event_loop_freeze_escalates_never_nudges() -> None:
    d = decide(
        snapshot=HealthSnapshot(event_loop_stalled=True), agent_actions=[], attempts={}
    )
    assert not d.nudges
    assert len(d.escalations) == 1
    assert d.escalations[0].blast == BLAST_HIGH


def test_green_while_dying_vitals_escalates_for_human_judgement() -> None:
    d = decide(
        snapshot=HealthSnapshot(vitals_verdict="diverging"), agent_actions=[], attempts={}
    )
    assert not d.nudges
    assert d.escalations[0].blast == BLAST_HIGH


# --- rules 4/5: bounded retries → give-up window escalates -------------------


def test_repeat_without_improvement_escalates_instead_of_looping() -> None:
    snap = HealthSnapshot(stalled_loops=["staging_bisect"])
    # First tick: within window → nudge.
    first = decide(snapshot=snap, agent_actions=[], attempts={})
    assert len(first.nudges) == 1 and not first.escalations
    # Second tick, same still-stalled loop, window exhausted → escalate, stop nudging.
    key = "stalled_loop:staging_bisect"
    second = decide(snapshot=snap, agent_actions=[], attempts={key: GIVEUP_CAP})
    assert not second.nudges
    assert len(second.escalations) == 1
    assert "give-up window" in second.escalations[0].escalate_reason.lower()


# --- rule 1: classify flake vs real -----------------------------------------


def test_classify_action_defers_recognized_transients() -> None:
    for reason in (
        "NodeSource 403 CDN flake",
        "xdist worker contamination",
        "flaky check on rerun",
    ):
        a = ProposedAction(kind="rerun_flaky_check", reason=reason)
        assert classify_action(a) == CLASS_TRANSIENT


def test_classify_action_defaults_ambiguous_to_real_actionable() -> None:
    # An unrecognized signal is treated as REAL — ambiguity must not be ignored.
    assert classify_action(ProposedAction(kind="restart_stalled_loop", reason="stuck")) == (
        CLASS_REAL
    )
    # An explicit agent hint wins over the substring scan.
    assert (
        classify_action(ProposedAction(kind="x", reason="stuck", signal_class="transient"))
        == CLASS_TRANSIENT
    )


def test_transient_agent_action_is_deferred_not_nudged() -> None:
    d = decide(
        snapshot=HealthSnapshot(),
        agent_actions=[
            ProposedAction(
                kind="rerun_flaky_check", reason="CDN 403 flake", signal_class="transient"
            )
        ],
        attempts={},
    )
    assert not d.nudges and not d.escalations
    assert len(d.deferred) == 1


# --- rules 2/3: escalate blast / drop cause-less ----------------------------


def test_blast_radius_agent_action_escalates() -> None:
    d = decide(
        snapshot=HealthSnapshot(),
        agent_actions=[
            ProposedAction(
                kind="force_push", target="main", reason="rebase main", blast=BLAST_HIGH
            )
        ],
        attempts={},
    )
    assert not d.nudges
    assert len(d.escalations) == 1


def test_non_allowlisted_agent_action_escalates_even_if_low_blast() -> None:
    d = decide(
        snapshot=HealthSnapshot(),
        agent_actions=[
            ProposedAction(kind="delete_branch", reason="cleanup", blast="low")
        ],
        attempts={},
    )
    assert not d.nudges
    assert len(d.escalations) == 1


def test_cause_less_action_is_dropped_as_noise() -> None:
    # rule 3: an allowlisted action with no diagnosis must NOT act.
    d = decide(
        snapshot=HealthSnapshot(),
        agent_actions=[ProposedAction(kind="restart_stalled_loop", target="x", reason="")],
        attempts={},
    )
    assert not d.nudges and not d.escalations
    assert len(d.deferred) == 1


# --- rule 8: verify + re-arm ------------------------------------------------


def test_reconcile_clears_a_healed_incident_and_resets_its_window() -> None:
    attempts = {"stalled_loop:staging_bisect": 1, "boot_sha_stale": 1}
    # This tick only staging_bisect is still stalled → boot_sha_stale healed.
    pruned, cleared = reconcile_ledger(attempts, active_keys={"stalled_loop:staging_bisect"})
    assert cleared == ["boot_sha_stale"]  # verified: a prior nudge worked
    assert pruned == {"stalled_loop:staging_bisect": 1}  # still-active keeps its count


def test_reconcile_noop_when_all_incidents_persist() -> None:
    attempts = {"a": 1, "b": 2}
    pruned, cleared = reconcile_ledger(attempts, active_keys={"a", "b"})
    assert cleared == []
    assert pruned == attempts
