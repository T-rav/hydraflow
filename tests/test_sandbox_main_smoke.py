"""sandbox_main bootstrap with empty seed — proves wiring resolves."""

from __future__ import annotations

import os
from types import SimpleNamespace
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


async def test_seeded_workspace_landed_proof_matches_only_exact_identity(
    tmp_path,
) -> None:
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    issue = 7301
    branch = f"agent/issue-{issue}"
    path = config.workspace_path_for_issue(issue)
    seed = MockWorldSeed(stale_workspaces=[{"number": issue, "branch": branch}])
    loop = SimpleNamespace()

    sandbox_main.wire_seeded_workspace_landed_proof(loop, config, seed)

    proof = loop._worktree_work_has_landed
    assert await proof(
        path,
        expected_branch=branch,
        expected_issue=issue,
    )
    assert not await proof(
        path,
        expected_branch="agent/issue-9999",
        expected_issue=issue,
    )
    assert not await proof(
        config.workspace_path_for_issue(9999),
        expected_branch=branch,
        expected_issue=issue,
    )


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


def test_materialize_prompt_telemetry_source_creates_verified_empty_ledger(
    tmp_path,
) -> None:
    """An opted-in sandbox proves zero bypass rows without inventing a row."""
    import json

    from mockworld.seed import MockWorldSeed
    from prompt_telemetry import (
        prompt_telemetry_health_path,
        prompt_telemetry_source_complete,
    )

    config = _seed_config(tmp_path)
    seed = MockWorldSeed(prompt_telemetry_source_initialized=True)

    sandbox_main.materialize_prompt_telemetry_source(config, seed)

    inference_path = config.cost_inferences_path
    assert inference_path.read_text() == ""
    marker = json.loads(prompt_telemetry_health_path(inference_path).read_text())
    assert marker["status"] == "healthy"
    assert marker["record_count"] == 0
    assert marker["chain_head"] is None
    assert prompt_telemetry_source_complete(inference_path) is True


def test_materialize_prompt_telemetry_source_noops_without_opt_in(tmp_path) -> None:
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)

    sandbox_main.materialize_prompt_telemetry_source(config, MockWorldSeed())

    assert not config.cost_inferences_path.exists()


def test_materialize_prompt_telemetry_source_refuses_corrupt_existing_ledger(
    tmp_path,
) -> None:
    """Scenario bootstrap must not turn missing evidence into false health."""
    import pytest

    from mockworld.seed import MockWorldSeed
    from prompt_telemetry import prompt_telemetry_source_complete

    config = _seed_config(tmp_path)
    inference_path = config.cost_inferences_path
    inference_path.parent.mkdir(parents=True, exist_ok=True)
    inference_path.write_text("{not-json}\n")
    seed = MockWorldSeed(prompt_telemetry_source_initialized=True)

    with pytest.raises(RuntimeError, match="Could not initialize healthy"):
        sandbox_main.materialize_prompt_telemetry_source(config, seed)

    assert inference_path.read_text() == "{not-json}\n"
    assert prompt_telemetry_source_complete(inference_path) is False


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


def test_resolve_self_wiki_root_falls_back_to_data_path_when_docs_wiki_absent(
    tmp_path,
) -> None:
    """#10133 PIECE 2 — no ``docs/wiki`` on disk (the sandbox image ships no
    ``docs/``) falls back to the runtime-cache ``config.data_path("repo_wiki")``.
    """
    config = _seed_config(tmp_path)

    wiki_root = sandbox_main.resolve_self_wiki_root(config)

    assert wiki_root == config.data_path("repo_wiki")


def test_resolve_self_wiki_root_prefers_docs_wiki_when_present(tmp_path) -> None:
    """#10133 PIECE 2 — a real ``docs/wiki`` (the self-repo's git-tracked
    wiki) wins over the runtime-cache fallback, mirroring
    ``service_registry.build_services``'s ``repo_wiki_store`` construction.
    """
    config = _seed_config(tmp_path)
    docs_wiki = config.repo_root / "docs" / "wiki"
    docs_wiki.mkdir(parents=True)

    wiki_root = sandbox_main.resolve_self_wiki_root(config)

    assert wiki_root == docs_wiki


def test_materialize_wiki_fixtures_noops_when_empty(tmp_path) -> None:
    """Empty ``repo_wiki_fixtures`` writes nothing (#10133 PIECE 2)."""
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)

    sandbox_main.materialize_wiki_fixtures(config, MockWorldSeed())

    assert not sandbox_main.resolve_self_wiki_root(config).exists()


def test_materialize_wiki_fixtures_round_trips_structured_wiki_entry(tmp_path) -> None:
    """A seeded fixture round-trips through a REAL ``RepoWikiStore.ingest``
    into the STRUCTURED ``WikiEntry`` shape ``WikiRotDetectorLoop`` consumes
    (issue #9936) — ``source_type``/``source_issue``/``fixed_in_pr``/
    ``code_refs`` all survive as modeled fields, not an unstructured blob
    (#10133 PIECE 2).
    """
    from mockworld.seed import MockWorldSeed
    from repo_wiki import RepoWikiStore

    config = _seed_config(tmp_path)
    slug = "acme/wiki-fixture-repo"
    broken_cite = (
        "src/wiki_rot_sandbox_fixture_module.py:wiki_rot_sandbox_fixture_symbol"
    )
    seed = MockWorldSeed(
        repo_wiki_fixtures=[
            {
                "repo_slug": slug,
                "title": "Broken cite fixture",
                "content": f"See `{broken_cite}` for the (missing) fix.",
                "source_type": "manual",
                "source_issue": 9999,
                "fixed_in_pr": "#9999",
                "code_refs": [broken_cite],
            }
        ]
    )

    sandbox_main.materialize_wiki_fixtures(config, seed)

    wiki_root = sandbox_main.resolve_self_wiki_root(config)
    assert wiki_root.exists()
    read_store = RepoWikiStore(
        wiki_root=wiki_root,
        tracked_root=config.repo_root / config.repo_wiki_path,
        self_slug=config.repo,
    )
    assert slug in read_store.list_repos()
    repo_dir = read_store.repo_dir(slug)
    entries = [
        entry
        for md_path in sorted(repo_dir.glob("*.md"))
        for entry in read_store.load_topic_entries(md_path)
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.title == "Broken cite fixture"
    assert entry.source_type == "manual"
    assert entry.source_issue == 9999
    assert entry.fixed_in_pr == "#9999"
    assert entry.code_refs == (broken_cite,)
    assert broken_cite in entry.content


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
    src/ and tests/ only), so the default must not depend on it.
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


def test_sandbox_overrides_disable_evidence_pack(tmp_path) -> None:
    """#10309: CH-4's raw ``gh`` reconcile sweep + compiler are air-gapped off.

    Both fire on every StagingPromotionLoop tick once ``staging_enabled`` is
    seeded true — ``_list_merged_promotion_prs`` is a raw ``gh pr list``
    subprocess (grandfathered spawn) that would hang-then-fail on the
    air-gapped network each cycle.
    """
    config = _seed_config(tmp_path)
    assert config.evidence_pack_enabled is True  # production default

    sandbox_main._apply_sandbox_config_overrides(config)

    assert config.evidence_pack_enabled is False


def test_seed_staging_enabled_applies_to_config(tmp_path) -> None:
    """#10309: ``seed.staging_enabled`` flips the config so the s82 scenario
    activates StagingPromotionLoop; the default leaves every other scenario
    in the historical ``staging_disabled`` no-op.

    ``staging_enabled`` now defaults ON in production, so the sandbox air-gap
    set (``_apply_sandbox_config_overrides``) pins it OFF first; the seed
    override then re-enables it only when the scenario asks for it.
    """
    from mockworld.seed import MockWorldSeed

    config = _seed_config(tmp_path)
    # Production default is ON; the air-gap set pins it back OFF.
    sandbox_main._apply_sandbox_config_overrides(config)
    assert config.staging_enabled is False

    sandbox_main.apply_seed_config_overrides(config, MockWorldSeed())
    assert config.staging_enabled is False

    sandbox_main.apply_seed_config_overrides(
        config, MockWorldSeed(staging_enabled=True)
    )
    assert config.staging_enabled is True


# ---------------------------------------------------------------------------
# #11298 light lane: AutoAgentPreflightLoop spawn air-gap
# ---------------------------------------------------------------------------


def _light_lane_world():
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.fakes.fake_llm import FakeLLM
    from tests.helpers import ConfigFactory

    github = FakeGitHub()
    github.add_issue(
        7, "Fix typo", "One-line copy fix.", labels=["hydraflow-auto-light"]
    )
    return FakeLLM(), github, ConfigFactory.create()


async def test_seeded_auto_agent_spawn_resolved_mints_pr_through_the_port() -> None:
    from mockworld.sandbox_main import build_seeded_auto_agent_spawn_builder
    from preflight.runner import parse_agent_response

    llm, github, config = _light_lane_world()
    llm.script_auto_agent(7, [{"status": "resolved", "diagnosis": "fixed"}])
    spawn = build_seeded_auto_agent_spawn_builder(llm, prs=github, config=config)(7)

    result = await spawn(prompt="do the thing", worktree_path="/tmp/wt")

    assert result.crashed is False
    parsed = parse_agent_response(result.output_text)
    assert parsed["status"] == "resolved"
    assert parsed["diagnosis"] == "fixed"
    pr = github.pr_for_issue(7)
    assert pr is not None, "resolved spawn must mint the PR via PRPort.create_pr"
    assert pr.branch == config.auto_agent_branch_for_issue(7)
    assert parsed["pr_url"] == pr.url
    assert result.prompt_hash.startswith("sha256:")
    assert llm.auto_agent_calls == [7]


async def test_seeded_auto_agent_spawn_honours_failure_scripts() -> None:
    from mockworld.sandbox_main import build_seeded_auto_agent_spawn_builder
    from preflight.runner import parse_agent_response

    llm, github, config = _light_lane_world()
    llm.script_auto_agent(
        7,
        [
            {
                "status": "needs_human",
                "blocked_reason": "needs_credentials",
                "diagnosis": "no token",
            },
            {"crashed": True, "output_text": "boom"},
        ],
    )
    build = build_seeded_auto_agent_spawn_builder(llm, prs=github, config=config)

    first = await build(7)(prompt="p", worktree_path="w")
    parsed = parse_agent_response(first.output_text)
    assert first.crashed is False
    assert parsed["status"] == "needs_human"
    assert parsed["blocked_reason"] == "needs_credentials"
    assert parsed["pr_url"] is None
    assert github.pr_for_issue(7) is None, "a non-resolve must not mint a PR"

    second = await build(7)(prompt="p", worktree_path="w")
    assert second.crashed is True
    assert second.output_text == "boom"


async def test_seeded_auto_agent_spawn_unscripted_is_crashed_and_logged(
    caplog,
) -> None:
    from mockworld.sandbox_main import build_seeded_auto_agent_spawn_builder

    llm, github, config = _light_lane_world()
    spawn = build_seeded_auto_agent_spawn_builder(llm, prs=github, config=config)(7)

    with caplog.at_level("WARNING", logger="hydraflow.sandbox_main"):
        result = await spawn(prompt="p", worktree_path="w")

    assert result.crashed is True
    assert "no scripted auto-agent spawn for issue #7" in caplog.text
    assert github.pr_for_issue(7) is None
    assert llm.auto_agent_calls == [7]


async def test_air_gap_runner_sentinels_rebinds_preflight_spawn_builder(
    tmp_path, monkeypatch
) -> None:
    """The shared air-gap helper must rebind ``_build_spawn_fn`` so the
    loop never constructs/runs a real ``AutoAgentRunner`` (#11298)."""
    from auto_agent_preflight_loop import AutoAgentPreflightLoop
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.fakes.fake_llm import FakeLLM
    from mockworld.sandbox_main import air_gap_runner_sentinels
    from preflight.audit import PreflightAuditStore
    from tests.helpers import make_bg_loop_deps

    deps = make_bg_loop_deps(tmp_path)
    github = FakeGitHub()
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=SimpleNamespace(),
        pr_manager=github,
        wiki_store=None,
        audit_store=PreflightAuditStore(deps.config.data_root),
        deps=deps.loop_deps,
    )

    async def _never(*_a, **_kw):
        raise AssertionError("real AutoAgentRunner.run reached under the air-gap")

    monkeypatch.setattr("preflight.auto_agent_runner.AutoAgentRunner.run", _never)
    svc = SimpleNamespace(
        health_monitor_loop=SimpleNamespace(),
        reviewers=SimpleNamespace(),
        planner_phase=SimpleNamespace(),
        implementer=SimpleNamespace(),
        diagnostic_loop=SimpleNamespace(),
        auto_agent_preflight_loop=loop,
    )
    llm = FakeLLM()

    air_gap_runner_sentinels(svc, llm)  # type: ignore[arg-type]

    assert "_build_spawn_fn" in vars(loop), "must be an instance-level rebinding"
    result = await loop._build_spawn_fn(5)(prompt="p", worktree_path="w")
    assert result.crashed is True  # unscripted → deterministic failure, no spawn
    assert llm.auto_agent_calls == [5]


def test_auto_agent_scripts_load_identically_through_both_seed_loaders(
    tmp_path,
) -> None:
    """Dual-loader parity: sandbox_main's generic ``script_<phase>`` dispatch
    and ``MockWorld.apply_seed`` must build the same auto_agent FIFO from the
    same JSON seed (int-coerced issue keys included)."""
    from mockworld.fakes.fake_llm import FakeLLM
    from mockworld.seed import MockWorldSeed
    from tests.scenarios.fakes.mock_world import MockWorld

    seed = MockWorldSeed.from_json(
        MockWorldSeed(
            issues=[{"number": 7, "title": "t", "body": "b", "labels": []}],
            scripts={"auto_agent": {7: [{"status": "retry"}, {"status": "resolved"}]}},
        ).to_json()
    )

    docker_llm = FakeLLM()
    for phase, by_issue in seed.scripts.items():  # sandbox_main.main()'s loop
        for issue_number, results in by_issue.items():
            getattr(docker_llm, f"script_{phase}")(issue_number, results)

    world = MockWorld(tmp_path).apply_seed(seed)

    assert dict(docker_llm.auto_agent) == dict(world._llm.auto_agent)
    assert list(world._llm.auto_agent[7]) == [
        {
            "status": "retry",
            "pr_url": None,
            "diagnosis": "",
            "confidence": "high",
            "blocked_reason": "none",
            "cost_usd": 0.0,
            "tokens": 0,
            "crashed": False,
            "output_text": None,
        },
        {
            "status": "resolved",
            "pr_url": None,
            "diagnosis": "",
            "confidence": "high",
            "blocked_reason": "none",
            "cost_usd": 0.0,
            "tokens": 0,
            "crashed": False,
            "output_text": None,
        },
    ]
