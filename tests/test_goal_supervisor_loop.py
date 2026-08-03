"""Unit tests for the Tier-2 goal supervisor (ADR-0124).

Split into two layers:

* the **pure decision core** in ``supervisor_observation`` (classify, known-
  incident derivation, nudge-vs-escalate routing, give-up window, verify/re-arm,
  thread + ledger IO) — the load-bearing safety, so it is exercised directly;
* the **loop** (``GoalSupervisorLoop``) actuating over that core — kill-switch
  (both), dry-run, healthy→no-op, degraded→nudges, blast-radius→escalates.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import credit_failover
from goal_supervisor_loop import GoalSupervisorLoop, NudgeResult
from supervisor_observation import (
    BLAST_HIGH,
    NUDGE_RESTART_STALLED_LOOP,
    HealthSnapshot,
    Incident,
    ProposedAction,
    SupervisorObservation,
    SupervisorVerdict,
    append_ack,
    append_observation,
    build_health_snapshot,
    classify_action,
    decide,
    derive_incidents,
    load_attempts,
    parse_supervisor_verdict,
    read_thread,
    reconcile_ledger,
    save_attempts,
    supervisor_thread_path,
)
from tests.helpers import make_bg_loop_deps

_NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Pure core — build_health_snapshot
# ---------------------------------------------------------------------------
def test_snapshot_flags_stalled_loop_beyond_3x_interval() -> None:
    old = (_NOW - timedelta(hours=6)).isoformat()
    snap = build_health_snapshot(
        heartbeats={"diagram_loop": {"status": "ok", "last_run": old}},
        intervals={"diagram_loop": 3600},  # 6h age > 3x 1h
        now=_NOW,
    )
    assert snap.stalled_loops == ["diagram_loop"]
    assert not snap.healthy


def test_snapshot_fresh_loop_is_healthy() -> None:
    recent = (_NOW - timedelta(minutes=1)).isoformat()
    snap = build_health_snapshot(
        heartbeats={"diagram_loop": {"status": "ok", "last_run": recent}},
        intervals={"diagram_loop": 3600},
        now=_NOW,
    )
    assert snap.stalled_loops == []
    assert snap.healthy


def test_snapshot_flags_error_loop_and_excludes_disabled() -> None:
    old = (_NOW - timedelta(hours=6)).isoformat()
    snap = build_health_snapshot(
        heartbeats={
            "a": {"status": "error", "last_run": old},
            "b": {"status": "disabled", "last_run": old},
        },
        intervals={"a": 3600, "b": 3600},
        now=_NOW,
    )
    assert snap.error_loops == ["a"]
    assert "b" not in snap.stalled_loops  # disabled never flagged
    assert not snap.healthy


def test_snapshot_boot_sha_stale_when_behind() -> None:
    snap = build_health_snapshot(
        heartbeats={}, intervals={}, now=_NOW, commits_behind=90
    )
    assert snap.boot_sha_stale
    assert not snap.healthy


def test_snapshot_diverging_vitals_is_unhealthy() -> None:
    snap = build_health_snapshot(
        heartbeats={}, intervals={}, now=_NOW, vitals_verdict="diverging"
    )
    assert not snap.healthy


# ---------------------------------------------------------------------------
# Pure core — classify (rule 1)
# ---------------------------------------------------------------------------
def test_classify_transient_by_signature() -> None:
    action = ProposedAction(
        kind="rerun_flaky_check", reason="NodeSource 403 flake on docker build"
    )
    assert classify_action(action) == "transient"


def test_classify_explicit_hint_wins() -> None:
    action = ProposedAction(kind="anything", reason="looks bad", signal_class="real")
    assert classify_action(action) == "real"


def test_classify_defaults_to_real() -> None:
    action = ProposedAction(kind="restart_stalled_loop", reason="loop wedged")
    assert classify_action(action) == "real"


# ---------------------------------------------------------------------------
# Pure core — derive_incidents (rule 7)
# ---------------------------------------------------------------------------
def test_derive_incidents_known_signatures() -> None:
    snap = HealthSnapshot(
        stalled_loops=["diagram_loop"],
        credit_probe_overdue=True,
        commits_behind=5,
        boot_sha_stale=True,
        event_loop_stalled=True,
    )
    keys = {inc.key for inc in derive_incidents(snap)}
    assert "stalled_loop:diagram_loop" in keys
    assert "credit_probe_overdue" in keys
    assert "boot_sha_stale" in keys
    assert "event_loop_stall" in keys
    # event-loop freeze is Tier-1's job → high blast
    freeze = next(i for i in derive_incidents(snap) if i.key == "event_loop_stall")
    assert freeze.blast == BLAST_HIGH


# ---------------------------------------------------------------------------
# Pure core — decide (rules 1-5)
# ---------------------------------------------------------------------------
def test_decide_nudges_tractable_reversible() -> None:
    snap = HealthSnapshot(stalled_loops=["diagram_loop"])
    dec = decide(snapshot=snap, agent_actions=[], attempts={})
    assert [i.key for i in dec.nudges] == ["stalled_loop:diagram_loop"]
    assert dec.escalations == []


def test_decide_escalates_blast_radius_even_if_allowlisted() -> None:
    snap = HealthSnapshot(stalled_loops=[])
    action = ProposedAction(
        kind=NUDGE_RESTART_STALLED_LOOP,
        target="x",
        reason="wedged",
        blast="high",  # high blast escalates despite allowlisted kind
    )
    dec = decide(snapshot=snap, agent_actions=[action], attempts={})
    assert dec.nudges == []
    assert len(dec.escalations) == 1


def test_decide_escalates_non_allowlisted_kind() -> None:
    snap = HealthSnapshot(stalled_loops=[])
    action = ProposedAction(kind="force_push", target="main", reason="rebase")
    dec = decide(snapshot=snap, agent_actions=[action], attempts={})
    assert dec.escalations[0].kind == "force_push"
    assert dec.nudges == []


def test_decide_escalates_after_giveup_window() -> None:
    snap = HealthSnapshot(stalled_loops=["diagram_loop"])
    # already at the cap → escalate instead of nudging again (rule 4/5)
    dec = decide(
        snapshot=snap,
        agent_actions=[],
        attempts={"stalled_loop:diagram_loop": 1},
        giveup_cap=1,
    )
    assert dec.nudges == []
    assert dec.escalations[0].key == "stalled_loop:diagram_loop"
    assert "give-up window exhausted" in dec.escalations[0].escalate_reason


def test_decide_defers_transient() -> None:
    snap = HealthSnapshot(stalled_loops=[])
    action = ProposedAction(
        kind="rerun_flaky_check", reason="flaky", signal_class="transient"
    )
    dec = decide(snapshot=snap, agent_actions=[action], attempts={})
    assert dec.nudges == []
    assert dec.escalations == []
    assert len(dec.deferred) == 1


def test_decide_defers_causeless_action() -> None:
    snap = HealthSnapshot(stalled_loops=[])
    action = ProposedAction(kind=NUDGE_RESTART_STALLED_LOOP, target="x", reason="")
    dec = decide(snapshot=snap, agent_actions=[action], attempts={})
    assert dec.nudges == []  # rule 3: no cause = noise
    assert len(dec.deferred) == 1


# ---------------------------------------------------------------------------
# Pure core — reconcile_ledger (rule 8), parsing, credit re-arm
# ---------------------------------------------------------------------------
def test_reconcile_ledger_clears_resolved_keys() -> None:
    pruned, cleared = reconcile_ledger(
        {"stalled_loop:a": 1, "boot_sha_stale": 1}, active_keys={"boot_sha_stale"}
    )
    assert pruned == {"boot_sha_stale": 1}
    assert cleared == ["stalled_loop:a"]


def test_parse_verdict_fenced_and_bare_and_invalid() -> None:
    fenced = parse_supervisor_verdict(
        'noise\n```json\n{"assessment": "ok", "actions": []}\n```'
    )
    assert fenced.assessment == "ok"
    bare = parse_supervisor_verdict('{"assessment": "bare"}')
    assert bare.assessment == "bare"
    invalid = parse_supervisor_verdict("not json at all")
    assert "no parseable verdict" in invalid.assessment


def test_credit_failover_rearm_probe() -> None:
    assert credit_failover.rearm_probe(now=_NOW) is False  # inactive
    credit_failover.engage(now=_NOW, resume_at=None, cooldown_minutes=15)
    assert credit_failover.rearm_probe(now=_NOW) is True
    assert credit_failover.probe_due(_NOW) is True  # now eligible


def test_thread_and_ledger_roundtrip(tmp_path: Path) -> None:
    deps = make_bg_loop_deps(tmp_path)
    config = deps.config
    obs = SupervisorObservation(assessment="hello", nudges_taken=["a"])
    append_observation(config, obs)
    append_observation(config, SupervisorObservation(assessment="world"))
    rows = read_thread(config, limit=10)
    assert [r["assessment"] for r in rows] == ["hello", "world"]
    assert supervisor_thread_path(config).exists()

    save_attempts(config, {"k": 3})
    assert load_attempts(config) == {"k": 3}


def test_read_thread_joins_acked_escalations(tmp_path: Path) -> None:
    """read_thread JOINs the ack log: only (ts, escalation)-matched rows mark."""
    deps = make_bg_loop_deps(tmp_path)
    config = deps.config
    obs = SupervisorObservation(
        ts="2026-08-02T12:00:00Z",
        assessment="RC wedged",
        escalations=["force_push [main]", "delete_branch [orphan]"],
    )
    append_observation(config, obs)

    # No acks yet → nothing joined.
    rows = read_thread(config)
    assert rows[0]["acked_escalations"] == []

    # Ack ONE of the two escalations; the other stays unacked.
    append_ack(config, ts="2026-08-02T12:00:00Z", escalation="force_push [main]")
    rows = read_thread(config)
    assert rows[0]["acked_escalations"] == ["force_push [main]"]
    # The original observation is untouched — both escalations still present.
    assert rows[0]["escalations"] == ["force_push [main]", "delete_branch [orphan]"]


def test_append_ack_matches_on_ts_and_escalation(tmp_path: Path) -> None:
    """An ack keyed to a different ts must NOT bleed onto another observation."""
    deps = make_bg_loop_deps(tmp_path)
    config = deps.config
    append_observation(
        config,
        SupervisorObservation(ts="2026-08-02T10:00:00Z", escalations=["force_push"]),
    )
    append_observation(
        config,
        SupervisorObservation(ts="2026-08-02T11:00:00Z", escalations=["force_push"]),
    )
    # Ack only the earlier observation's escalation.
    append_ack(config, ts="2026-08-02T10:00:00Z", escalation="force_push")
    rows = read_thread(config)
    by_ts = {r["ts"]: r for r in rows}
    assert by_ts["2026-08-02T10:00:00Z"]["acked_escalations"] == ["force_push"]
    assert by_ts["2026-08-02T11:00:00Z"]["acked_escalations"] == []


def test_read_thread_tolerates_missing_acks_file(tmp_path: Path) -> None:
    """A thread with no acks file joins to empty acked lists, never raises."""
    deps = make_bg_loop_deps(tmp_path)
    config = deps.config
    append_observation(
        config, SupervisorObservation(ts="2026-08-02T12:00:00Z", escalations=["x"])
    )
    rows = read_thread(config)
    assert rows[0]["acked_escalations"] == []


# ---------------------------------------------------------------------------
# Loop helpers
# ---------------------------------------------------------------------------
class _FakeState:
    def __init__(self, heartbeats: dict[str, Any], vitals: str = "green") -> None:
        self._hb = heartbeats
        self._vitals = vitals

    def get_worker_heartbeats(self) -> dict[str, Any]:
        return self._hb

    def get_second_order_vitals_last_verdict(self) -> str:
        return self._vitals


class _FakeRunner:
    def __init__(self, verdict: SupervisorVerdict) -> None:
        self.verdict = verdict
        self.calls = 0

    async def run(self, *, prompt: str, worktree_path: str, issue_number: int) -> Any:
        self.calls += 1
        return self.verdict


class _FakeNudger:
    def __init__(self) -> None:
        self.executed: list[Incident] = []

    async def execute(self, inc: Incident) -> NudgeResult:
        self.executed.append(inc)
        return NudgeResult(True, f"faked {inc.kind}")


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    config_enabled: bool = True,
    dry_run: bool = False,
    state: Any = None,
    runner: Any = None,
    nudger: Any = None,
) -> tuple[GoalSupervisorLoop, Any]:
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, dry_run=dry_run)
    deps.config.goal_supervisor_loop_enabled = config_enabled
    loop = GoalSupervisorLoop(
        config=deps.config,
        deps=deps.loop_deps,
        state=state,
        runner=runner,
        nudger=nudger,
        now_fn=lambda: _NOW,
    )
    return loop, deps.config


def _hermetic_git(monkeypatch: Any) -> None:
    """Neutralize real git reads so snapshots stay hermetic in tests."""
    import git_revision

    monkeypatch.setattr(git_revision, "get_boot_sha", lambda: None)
    monkeypatch.setattr(git_revision, "get_commits_behind", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Loop — kill-switch, dry-run, healthy, degraded, blast-radius
# ---------------------------------------------------------------------------
async def test_operator_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    assert await loop._do_work() == {"status": "disabled"}


async def test_config_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, config_enabled=False)
    assert await loop._do_work() == {"status": "config_disabled"}


async def test_dry_run_is_noop(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, dry_run=True)
    assert await loop._do_work() is None


async def test_healthy_snapshot_is_noop_no_agent_call(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _hermetic_git(monkeypatch)
    recent = (_NOW - timedelta(minutes=1)).isoformat()
    state = _FakeState({"diagram_loop": {"status": "ok", "last_run": recent}})
    runner = _FakeRunner(SupervisorVerdict(assessment="unused"))
    loop, config = _make_loop(tmp_path, state=state, runner=runner)
    result = await loop._do_work()
    assert result == {"status": "healthy"}
    assert runner.calls == 0  # agent is NOT consulted when healthy
    assert read_thread(config) == []  # no observation written


async def test_degraded_snapshot_takes_nudge(tmp_path: Path, monkeypatch: Any) -> None:
    _hermetic_git(monkeypatch)
    state = _FakeState({"a": {"status": "error", "last_run": _NOW.isoformat()}})
    runner = _FakeRunner(SupervisorVerdict(assessment="loop a errored"))
    nudger = _FakeNudger()
    loop, config = _make_loop(tmp_path, state=state, runner=runner, nudger=nudger)

    result = await loop._do_work()

    assert result["status"] == "acted"
    assert result["nudges"] == 1
    assert runner.calls == 1  # degraded → agent consulted
    assert [inc.kind for inc in nudger.executed] == [NUDGE_RESTART_STALLED_LOOP]
    rows = read_thread(config)
    assert len(rows) == 1
    assert rows[0]["nudges_taken"]  # honest thread records the nudge
    # give-up ledger recorded the attempt for verification next tick (rule 8)
    assert load_attempts(config) == {"error_loop:a": 1}


async def test_blast_radius_action_escalates(tmp_path: Path, monkeypatch: Any) -> None:
    _hermetic_git(monkeypatch)
    # snapshot degraded (error loop) so the agent is consulted; the agent also
    # proposes a blast-radius action which MUST be surfaced, not self-done.
    state = _FakeState({"a": {"status": "error", "last_run": _NOW.isoformat()}})
    verdict = SupervisorVerdict(
        assessment="danger",
        actions=[
            ProposedAction(
                kind="force_push", target="main", reason="rebase main", blast="high"
            )
        ],
    )
    nudger = _FakeNudger()
    loop, config = _make_loop(
        tmp_path, state=state, runner=_FakeRunner(verdict), nudger=nudger
    )

    result = await loop._do_work()

    assert result["escalations"] >= 1
    rows = read_thread(config)
    escalations = rows[0]["escalations"]
    assert any("force_push" in e for e in escalations)
    # the blast-radius action was never executed as a nudge
    assert all(inc.kind != "force_push" for inc in nudger.executed)


async def test_giveup_window_escalates_on_repeat(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _hermetic_git(monkeypatch)
    state = _FakeState({"a": {"status": "error", "last_run": _NOW.isoformat()}})
    runner = _FakeRunner(SupervisorVerdict(assessment="still errored"))
    nudger = _FakeNudger()
    loop, config = _make_loop(tmp_path, state=state, runner=runner, nudger=nudger)

    first = await loop._do_work()
    assert first["nudges"] == 1  # first tick nudges
    second = await loop._do_work()
    # incident persisted → give-up window exhausted → escalate, no new nudge
    assert second["nudges"] == 0
    assert second["escalations"] >= 1
    assert len(nudger.executed) == 1  # only nudged once, then escalated
