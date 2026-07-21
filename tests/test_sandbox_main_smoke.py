"""sandbox_main bootstrap with empty seed — proves wiring resolves."""

from __future__ import annotations

import os
from unittest.mock import patch

from mockworld import sandbox_main
from mockworld.sandbox_main import _build_caretaker_enabled_cb


def test_load_seed_returns_empty_when_no_path() -> None:
    with (
        patch.object(sandbox_main.sys, "argv", ["sandbox_main"]),
        patch.dict(os.environ, {}, clear=False),
    ):
        # Clear the env var if set
        os.environ.pop("HYDRAFLOW_MOCKWORLD_SEED", None)
        seed = sandbox_main._load_seed()
    assert seed.issues == []
    assert seed.prs == []


def test_load_seed_reads_file_path_from_argv(tmp_path) -> None:
    seed_path = tmp_path / "scenario.json"
    seed_path.write_text(
        '{"repos": [], "issues": [{"number": 1, "title": "t", "body": "b", "labels": []}],'
        ' "prs": [], "scripts": {}, "cycles_to_run": 4, "loops_enabled": null}'
    )
    with patch.object(sandbox_main.sys, "argv", ["sandbox_main", str(seed_path)]):
        seed = sandbox_main._load_seed()
    assert len(seed.issues) == 1
    assert seed.issues[0]["number"] == 1


def test_caretaker_enabled_cb_none_enables_all() -> None:
    """``loops_enabled=None`` (default) → every caretaker enabled."""
    cb = _build_caretaker_enabled_cb(None)
    assert cb("workspace_gc") is True
    assert cb("dependabot_merge") is True
    assert cb("anything_else") is True


def test_caretaker_enabled_cb_empty_disables_all() -> None:
    """``loops_enabled=[]`` → universal kill-switch (ADR-0049, #8483).

    Every caretaker name returns False so their in-body
    ``self._enabled_cb(self._worker_name)`` gate trips and no ``_do_work``
    runs. Phase orchestrators are not gated by this callback (they use
    ``BGWorkerManager.is_enabled`` via the orchestrator), so they remain
    unaffected — that's the per-#8483-triage-comment contract.
    """
    cb = _build_caretaker_enabled_cb([])
    assert cb("workspace_gc") is False
    assert cb("dependabot_merge") is False
    assert cb("ci_monitor") is False


def test_caretaker_enabled_cb_subset_enables_only_named() -> None:
    """``loops_enabled=["x","y"]`` → only x and y caretakers enabled."""
    cb = _build_caretaker_enabled_cb(["dependabot_merge", "workspace_gc"])
    assert cb("dependabot_merge") is True
    assert cb("workspace_gc") is True
    assert cb("ci_monitor") is False
    assert cb("sentry_ingest") is False


def test_caretaker_enabled_cb_tolerates_extra_args() -> None:
    """The callback is invoked from ``LoopDeps.enabled_cb`` which historically
    took ``(name)`` but some call sites pass extra positional/keyword args.
    Match the prior ``lambda *_a, **_kw: True`` tolerance.
    """
    cb_all = _build_caretaker_enabled_cb(None)
    cb_subset = _build_caretaker_enabled_cb(["workspace_gc"])
    # Should not raise.
    assert cb_all("workspace_gc", "extra", key="val") is True
    assert cb_subset("workspace_gc", "extra", key="val") is True
    assert cb_subset("other", "extra", key="val") is False


# --- #9543 active-trigger seed seams -----------------------------------------


def _seed_config(tmp_path):
    from tests.helpers import make_bg_loop_deps

    return make_bg_loop_deps(tmp_path).config


def test_seed_stale_workspaces_populates_state(tmp_path) -> None:
    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)
    seed = MockWorldSeed(
        stale_workspaces=[{"number": 7301, "branch": "agent/issue-7301"}]
    )

    sandbox_main.seed_stale_workspaces(state, config, seed)

    workspaces = state.get_active_workspaces()
    assert 7301 in workspaces
    expected = config.workspace_base / config.repo_slug / "issue-7301"
    assert workspaces[7301] == str(expected)
    assert state.get_active_branches()[7301] == "agent/issue-7301"


def test_seed_stale_workspaces_defaults_branch_and_noops_when_empty(
    tmp_path,
) -> None:
    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)

    sandbox_main.seed_stale_workspaces(state, config, MockWorldSeed())
    assert state.get_active_workspaces() == {}

    seed = MockWorldSeed(stale_workspaces=[{"number": 42}])
    sandbox_main.seed_stale_workspaces(state, config, seed)
    assert state.get_active_branches()[42] == "agent/issue-42"


def test_materialize_expired_runs_creates_purgeable_dir(tmp_path) -> None:
    from mockworld.seed import MockWorldSeed
    from run_recorder import RunRecorder

    config = _seed_config(tmp_path)
    seed = MockWorldSeed(expired_run_dirs=[{"issue": 7501, "age_days": 3650}])

    sandbox_main.materialize_expired_runs(config, seed)

    issue_dir = config.repo_data_path("runs") / "7501"
    run_dirs = list(issue_dir.iterdir())
    assert len(run_dirs) == 1
    # The materialized run is genuinely expired: a purge cycle removes it.
    recorder = RunRecorder(config)
    assert recorder.purge_expired(config.artifact_retention_days) == 1
    assert not issue_dir.exists()


def test_materialize_expired_runs_noops_when_empty(tmp_path) -> None:
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    sandbox_main.materialize_expired_runs(config, MockWorldSeed())
    assert not (config.repo_data_path("runs")).exists()


# --- #9643 state/JSONL materializer seams ------------------------------------


def test_materialize_epic_states_backdates_relative_age(tmp_path) -> None:
    """``last_activity_age_days`` becomes a tz-aware back-dated timestamp.

    Relative offsets keep seeds time-independent, and the materializer-minted
    timestamp is always tz-aware — a naive one would make
    ``EpicManager._is_stale`` swallow a ``TypeError`` and read the epic as
    fresh (the s71 silent-timeout footgun).
    """
    from datetime import UTC, datetime, timedelta

    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)
    seed = MockWorldSeed(
        epic_states=[
            {"epic_number": 7601, "last_activity_age_days": 3650, "child_issues": []}
        ]
    )

    sandbox_main.materialize_epic_states(state, seed)

    epic = state.get_epic_state(7601)
    assert epic is not None
    last = datetime.fromisoformat(epic.last_activity)
    assert last.tzinfo is not None
    assert last < datetime.now(UTC) - timedelta(days=3000)
    # The seed-only age key never leaks into the persisted model.
    assert not hasattr(epic, "last_activity_age_days")


def test_materialize_epic_states_passthrough_and_noop(tmp_path) -> None:
    """No age key → the payload reaches ``model_validate`` untouched; an
    empty seed writes no state."""
    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)

    sandbox_main.materialize_epic_states(state, MockWorldSeed())
    assert state.get_all_epic_states() == {}

    stamp = "2020-01-01T00:00:00+00:00"
    seed = MockWorldSeed(
        epic_states=[{"epic_number": 42, "title": "t", "last_activity": stamp}]
    )
    sandbox_main.materialize_epic_states(state, seed)
    epic = state.get_epic_state(42)
    assert epic is not None
    assert epic.last_activity == stamp
    assert epic.title == "t"


def test_materialize_health_metrics_writes_loop_read_paths(tmp_path) -> None:
    """Each artifact lands exactly where HealthMonitorLoop reads it.

    ``outcomes.jsonl`` + ``item_scores.json`` are FLAT under ``memory_dir``;
    ``harness_failures.jsonl`` is repo-scoped under ``repo_memory_dir`` —
    a wrong root yields a silently-idle loop reading zero metrics.
    """
    from health_monitor_loop import compute_trend_metrics
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    outcomes = [{"outcome": "failure"} for _ in range(9)] + [{"outcome": "success"}]
    seed = MockWorldSeed(
        health_metrics={
            "outcomes": outcomes,
            "item_scores": {"pattern-1": {"score": 0.8, "appearances": 3}},
            "harness_failures": [{"category": "hitl_escalation"}],
        }
    )

    sandbox_main.materialize_health_metrics(config, seed)

    assert (config.memory_dir / "outcomes.jsonl").exists()
    assert (config.memory_dir / "item_scores.json").exists()
    assert (config.repo_memory_dir / "harness_failures.jsonl").exists()
    metrics = compute_trend_metrics(
        config.memory_dir / "outcomes.jsonl",
        config.memory_dir / "item_scores.json",
        config.repo_memory_dir / "harness_failures.jsonl",
    )
    assert metrics.total_outcomes == 10
    assert metrics.first_pass_rate == 0.1  # < 0.2 → first_pass_rate_low fires
    assert metrics.avg_memory_score == 0.8
    assert metrics.hitl_escalation_rate == 1.0


def test_materialize_health_metrics_unknown_key_fails_closed(tmp_path) -> None:
    import pytest

    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    seed = MockWorldSeed(health_metrics={"outcoms": [{"outcome": "failure"}]})

    with pytest.raises(ValueError, match="outcoms"):
        sandbox_main.materialize_health_metrics(config, seed)


def test_materialize_health_metrics_noops_when_empty(tmp_path) -> None:
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)

    sandbox_main.materialize_health_metrics(config, MockWorldSeed())

    assert not (config.memory_dir / "outcomes.jsonl").exists()
    assert not (config.memory_dir / "item_scores.json").exists()
    assert not (config.repo_memory_dir / "harness_failures.jsonl").exists()


def test_materialize_worker_heartbeats_backdates_last_run(tmp_path) -> None:
    """``age_seconds`` becomes a tz-aware back-dated ``last_run``; empty
    seeds write nothing (#9643/#9904)."""
    from datetime import UTC, datetime, timedelta

    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)

    sandbox_main.materialize_worker_heartbeats(state, MockWorldSeed())
    assert state.get_worker_heartbeats() == {}

    seed = MockWorldSeed(
        worker_heartbeats={
            "epic_monitor": {
                "status": "running",
                "age_seconds": 7200,
                "details": {"stale_count": 0},
            },
            "runs_gc": {},  # all defaults: running, age 0, no details
        }
    )
    sandbox_main.materialize_worker_heartbeats(state, seed)

    beats = state.get_worker_heartbeats()
    aged = beats["epic_monitor"]
    assert aged["status"] == "running"
    assert aged["details"] == {"stale_count": 0}
    last_run = datetime.fromisoformat(aged["last_run"])
    assert last_run.tzinfo is not None
    assert last_run < datetime.now(UTC) - timedelta(seconds=7000)
    fresh = datetime.fromisoformat(beats["runs_gc"]["last_run"])
    assert fresh > datetime.now(UTC) - timedelta(seconds=60)


def test_materialize_worker_status_history_noops_when_empty(tmp_path) -> None:
    """Empty ``worker_status_history`` writes nothing to the event log (#10133)."""
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)

    sandbox_main.materialize_worker_status_history(config, MockWorldSeed())

    assert not config.event_log_path.exists()


def test_materialize_worker_status_history_writes_backdated_rows(tmp_path) -> None:
    """Seeded entries land as BACKGROUND_WORKER_STATUS rows on disk, with a
    relative ``age_seconds`` back-dating the row's timestamp from boot, and
    the loop's OWN read path (``EventBus.load_events_since``) can see them
    back (#10133) — the read side ``worker_heartbeats``/``registered_workers``
    never had to prove, since those are read straight off ``StateTracker``.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta

    from events import EventBus, EventLog, EventType
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    seed = MockWorldSeed(
        worker_status_history={
            "corpus_learning": [
                {"age_seconds": 82_800, "status": "error", "details": {}},
                {"age_seconds": 3_600, "status": "ok", "details": {"filed": 2}},
            ],
        }
    )

    sandbox_main.materialize_worker_status_history(config, seed)

    assert config.event_log_path.exists()
    event_bus = EventBus(event_log=EventLog(config.event_log_path))
    events = asyncio.run(
        event_bus.load_events_since(datetime.now(UTC) - timedelta(days=1))
    )
    assert events is not None
    assert len(events) == 2
    by_status = {e.data["status"]: e for e in events}
    assert set(by_status) == {"error", "ok"}
    error_event = by_status["error"]
    assert error_event.type == EventType.BACKGROUND_WORKER_STATUS
    assert error_event.data["worker"] == "corpus_learning"
    assert error_event.data["details"] == {}
    error_ts = datetime.fromisoformat(error_event.timestamp)
    assert error_ts.tzinfo is not None
    assert error_ts < datetime.now(UTC) - timedelta(seconds=82_000)
    ok_event = by_status["ok"]
    assert ok_event.data["details"] == {"filed": 2}
    ok_ts = datetime.fromisoformat(ok_event.timestamp)
    assert ok_ts > datetime.now(UTC) - timedelta(seconds=3_700)


def test_materialize_registered_workers_noops_when_empty(tmp_path) -> None:
    """Empty ``registered_workers`` returns ``None`` — no ``BGWorkerManager``
    is constructed and no state is touched (#10086)."""
    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)

    result = sandbox_main.materialize_registered_workers(state, config, MockWorldSeed())

    assert result is None
    assert state.get_disabled_workers() == set()


def test_materialize_registered_workers_builds_registered_loop_set(tmp_path) -> None:
    """Seeded names become BGWorkerManager's ``registered_loop_names()``; the
    duck-typed stand-in honors per-entry interval/timeout overrides and falls
    back to 60s for an empty entry (#10086)."""
    from mockworld.seed import MockWorldSeed
    from state import StateTracker

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)
    seed = MockWorldSeed(
        registered_workers={
            "workspace_gc": {"interval_seconds": 5, "cycle_timeout_seconds": 5},
            "runs_gc": {},  # defaults: 60s / 60s
        }
    )

    bg_workers = sandbox_main.materialize_registered_workers(state, config, seed)

    assert bg_workers is not None
    assert bg_workers.registered_loop_names() == {"workspace_gc", "runs_gc"}
    assert bg_workers.get_interval("workspace_gc") == 5
    assert bg_workers.cycle_timeout("workspace_gc") == 5
    assert bg_workers.get_interval("runs_gc") == 60
    assert bg_workers.cycle_timeout("runs_gc") == 60
    assert bg_workers.run_started_at("workspace_gc") is None
    # A name absent from the seed is simply unregistered — not an error.
    assert "epic_monitor" not in bg_workers.registered_loop_names()


async def test_registered_workers_seed_drives_stall_escalation_end_to_end(
    tmp_path,
) -> None:
    """The gap #10086 closes: a seeded registered worker + a stale seeded
    heartbeat together reach ``HealthMonitorLoop``'s generic dead-man-switch
    escalation — proving the seed can now express BGWorkerManager's
    registered-worker SET, not just the heartbeat read path (#9643/#9904).

    Before this materializer, ``worker_heartbeats`` alone could never
    traverse ``_check_worker_staleness``'s ``name not in registered`` filter
    (``bg_workers`` stays ``None`` unless the seed also seeds the registered
    set), so the restart/escalate branch was unreachable from a seed.
    """
    from unittest.mock import AsyncMock

    from health_monitor_loop import HealthMonitorLoop
    from mockworld.seed import MockWorldSeed
    from state import StateTracker
    from tests.helpers import make_bg_loop_deps

    config = _seed_config(tmp_path)
    state = StateTracker(config.state_file)
    seed = MockWorldSeed(
        registered_workers={
            "workspace_gc": {"interval_seconds": 5, "cycle_timeout_seconds": 5},
        },
        worker_heartbeats={
            # threshold = 3 * 5 + 5 = 20s; 99_999s is far past it.
            "workspace_gc": {"status": "ok", "age_seconds": 99_999},
        },
    )

    sandbox_main.materialize_worker_heartbeats(state, seed)
    bg_workers = sandbox_main.materialize_registered_workers(state, config, seed)
    assert bg_workers is not None
    # No restart_cb wired (mirrors sandbox_main/mock_world's minimal seam) —
    # ``bg_workers.restart()`` returns False, so the sweep escalates on the
    # very first stale cycle instead of restart-then-wait-a-sweep.

    deps = make_bg_loop_deps(tmp_path).loop_deps
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=99)

    loop = HealthMonitorLoop(config=config, deps=deps, prs=prs, state=state)
    loop.set_bg_workers(bg_workers)

    await loop._check_worker_staleness()

    prs.create_issue.assert_awaited_once()
    title, _body, labels = prs.create_issue.await_args.args
    assert "workspace_gc" in title
    assert "loop-stalled" in labels


def test_build_seeded_gate_detector_returns_proposals() -> None:
    import asyncio

    detector = sandbox_main.build_seeded_gate_detector(
        [
            {
                "name": "mockworld-scenarios",
                "dimension": "tests",
                "required_on": ["main", "staging"],
                "workflow": "test.yml",
                "job": "scenario-tests",
                "make_target": "scenario",
            }
        ]
    )

    proposals = asyncio.run(detector())

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.name == "mockworld-scenarios"
    assert proposal.required_on == ("main", "staging")  # tuple-coerced
    assert proposal.workflow == "test.yml"
    assert proposal.job == "scenario-tests"


def _write_canonical(tmp_path):
    import json

    canonical = {
        "name": "main protect",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}],
    }
    staging = dict(canonical, name="staging protect")
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    (canonical_dir / "main_ruleset.json").write_text(json.dumps(canonical))
    (canonical_dir / "staging_ruleset.json").write_text(json.dumps(staging))
    return canonical_dir, canonical, staging


def test_build_seeded_branch_protection_auditor_reports_drift(tmp_path) -> None:
    import asyncio

    from mockworld.fakes import FakeGitHub

    config = _seed_config(tmp_path)
    canonical_dir, _canonical, _staging = _write_canonical(tmp_path)
    gh = FakeGitHub()
    gh.add_ruleset(
        "main protect",
        {
            "name": "main protect",
            "target": "branch",
            "enforcement": "disabled",  # drifted
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
            "rules": [],
        },
    )
    auditor = sandbox_main.build_seeded_branch_protection_auditor(
        config, gh, canonical_dir=canonical_dir
    )

    report = asyncio.run(auditor())

    assert not report.clean
    # Both drift signals: the divergent main ruleset and the missing staging one.
    assert any("staging protect" in d and "missing" in d for d in report.drifts)


def test_build_seeded_branch_protection_auditor_clean_when_matching(
    tmp_path,
) -> None:
    import asyncio

    from mockworld.fakes import FakeGitHub

    config = _seed_config(tmp_path)
    canonical_dir, canonical, staging = _write_canonical(tmp_path)
    gh = FakeGitHub()
    gh.add_ruleset("main protect", canonical)
    gh.add_ruleset("staging protect", staging)
    auditor = sandbox_main.build_seeded_branch_protection_auditor(
        config, gh, canonical_dir=canonical_dir
    )

    report = asyncio.run(auditor())

    assert report.clean


def test_sandbox_overrides_disable_approval_records(tmp_path) -> None:
    """#9543: the CH-2 reconciler's raw ``gh`` boundary is config-disabled."""
    config = _seed_config(tmp_path)
    assert config.approval_records_enabled is True  # production default

    sandbox_main._apply_sandbox_config_overrides(config)

    assert config.approval_records_enabled is False


def test_auditor_defaults_to_materialized_canonical_baseline(tmp_path) -> None:
    """No canonical_dir: the fixed baseline is materialized under data root.

    The sandbox image ships no repo ``docs/`` (Dockerfile.agent copies only
    src/tests/templates/static), so the default must not depend on it.
    """
    import asyncio

    from mockworld.fakes import FakeGitHub

    config = _seed_config(tmp_path)
    gh = FakeGitHub()
    gh.add_ruleset(
        "main protect",
        {
            "name": "main protect",
            "target": "branch",
            "enforcement": "disabled",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
            "rules": [],
        },
    )
    auditor = sandbox_main.build_seeded_branch_protection_auditor(config, gh)

    report = asyncio.run(auditor())

    canonical_dir = config.repo_data_path("sandbox_canonical_rulesets")
    assert (canonical_dir / "main_ruleset.json").exists()
    assert (canonical_dir / "staging_ruleset.json").exists()
    assert not report.clean  # drifted main + missing staging vs the baseline
