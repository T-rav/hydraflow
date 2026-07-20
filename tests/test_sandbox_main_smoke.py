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
