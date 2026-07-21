"""MockWorldSeed — serializable initial state for a sandbox scenario."""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed


def test_default_seed_is_empty() -> None:
    seed = MockWorldSeed()
    assert seed.repos == []
    assert seed.issues == []
    assert seed.prs == []
    assert seed.scripts == {}
    assert seed.cycles_to_run == 4
    assert seed.loops_enabled is None
    assert seed.plan_hold_seconds == 0.0
    assert seed.rulesets == {}


def test_seed_round_trips_through_json() -> None:
    original = MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={"plan": {1: [{"success": True}]}},
        cycles_to_run=10,
        loops_enabled=["triage_loop"],
    )

    raw = original.to_json()
    parsed = MockWorldSeed.from_json(raw)

    assert parsed == original


def test_seed_json_is_valid_json() -> None:
    seed = MockWorldSeed(issues=[{"number": 1}])
    raw = seed.to_json()
    parsed = json.loads(raw)
    assert parsed["issues"] == [{"number": 1}]


def test_seed_round_trips_plan_hold_seconds_through_json() -> None:
    """Back-compat default (0.0) round-trips; a scenario-set value survives too."""
    original = MockWorldSeed(plan_hold_seconds=3.0)

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.plan_hold_seconds == 3.0


def test_default_seed_has_empty_rulesets() -> None:
    """Back-compat: every pre-#9644 scenario seed predates ``rulesets``."""
    assert MockWorldSeed().rulesets == {}


def test_seed_round_trips_rulesets_through_json() -> None:
    """JSON round-trip preserves the branch-protection ruleset seed (#9644).

    Ruleset names are string object keys and every value is JSON-native
    (nested dicts/lists), so no ``from_json`` key coercion is required — the
    equality check guards against a future field that would need it.
    """
    original = MockWorldSeed(
        rulesets={
            "staging protect": {
                "name": "staging protect",
                "target": "branch",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/heads/staging"]}},
                "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
            },
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original


def test_default_seed_has_empty_advisor_scripts() -> None:
    """Back-compat: every existing scenario seed predates ``advisor_scripts``."""
    assert MockWorldSeed().advisor_scripts == {}


def test_seed_round_trips_advisor_scripts_through_json() -> None:
    """JSON serialization preserves the (issue, role, payloads) advisor shape.

    Issue numbers are JSON object keys (always strings on the wire); the
    ``from_json`` coercion is what makes ``script_advisor(7, ...)`` —
    which expects an ``int`` issue number — work after a sandbox boot.
    """
    payload = json.dumps({"verdict": "APPROVE", "disagreements": []})
    original = MockWorldSeed(
        advisor_scripts={
            7: {"post_verify": [payload]},
            12: {"pre_flight": [payload], "mid_flight": [payload, payload]},
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert isinstance(next(iter(parsed.advisor_scripts.keys())), int)


def test_default_seed_has_empty_prompt_refine_seam() -> None:
    """Back-compat: seeds predating the prompt-refine air-gap seam (#9724)
    carry no corpus cases and an empty scripted patch."""
    seed = MockWorldSeed()
    assert seed.skill_prompt_corpus_cases == []
    assert seed.skill_prompt_refine_patch == ""


def test_seed_round_trips_prompt_refine_seam_through_json() -> None:
    """The scripted corpus regression + refine patch survive JSON transfer so
    the docker loader (sandbox_main) rebuilds the s56 refine seam faithfully."""
    original = MockWorldSeed(
        skill_prompt_corpus_cases=[
            {"case_id": "c1", "skill": "diff-sanity", "status": "FAIL"},
        ],
        skill_prompt_refine_patch="```diff\n--- a/x\n+++ b/x\n```\n",
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.skill_prompt_corpus_cases[0]["status"] == "FAIL"
    assert parsed.skill_prompt_refine_patch.startswith("```diff")


def test_default_seed_has_empty_phase_scripts() -> None:
    """Back-compat: pre-ADR-0063 seeds carry no phase_scripts entry."""
    assert MockWorldSeed().phase_scripts == {}


def test_seed_round_trips_phase_scripts_through_json() -> None:
    """JSON round-trip preserves the ADR-0063 phase_scripts shape.

    Inner keys are issue numbers (string on the wire, int after parse).
    The ``shape_council`` inner-inner keys are round numbers and also need
    string→int coercion so ``shape_council_verdict_for_round(issue, 1)``
    sees an int round number after a sandbox boot.
    """
    original = MockWorldSeed(
        phase_scripts={
            "discover": {
                1: [{"coherent": False, "queries_required": ["q1"]}],
            },
            "plan_review": {
                2: [{"verdict": "reject", "gaps": ["g1"]}],
            },
            "shape_council": {
                3: {1: "split", 2: "consensus"},
            },
            "implement_spec_review": {
                4: [{"compliant": False, "gaps": ["missing X"]}],
            },
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed.phase_scripts["discover"][1] == [
        {"coherent": False, "queries_required": ["q1"]}
    ]
    assert parsed.phase_scripts["plan_review"][2] == [
        {"verdict": "reject", "gaps": ["g1"]}
    ]
    assert parsed.phase_scripts["shape_council"][3] == {1: "split", 2: "consensus"}
    assert parsed.phase_scripts["implement_spec_review"][4] == [
        {"compliant": False, "gaps": ["missing X"]}
    ]
    # Issue keys must be ints (not the JSON string they were on the wire).
    assert all(isinstance(k, int) for k in parsed.phase_scripts["discover"])
    # shape_council round keys must also be ints (used for direct lookup).
    assert all(isinstance(rk, int) for rk in parsed.phase_scripts["shape_council"][3])


def test_default_seed_has_empty_issue_refinement_seam() -> None:
    """Back-compat: seeds predating the issue-refinement air-gap seam (#9957)
    carry no backlog and no scripted verdicts."""
    seed = MockWorldSeed()
    assert seed.issue_refinement_backlog == []
    assert seed.issue_refinement_verdicts == []


def test_seed_round_trips_issue_refinement_seam_through_json() -> None:
    """The seeded backlog + scripted dup verdicts survive JSON transfer so the
    docker loader (sandbox_main) rebuilds the s57 refinement seam faithfully.

    Backlog issue numbers are JSON VALUES (not object keys), so they stay ``int``
    across the wire with no ``from_json`` coercion — the equality check guards a
    future shape that would need it.
    """
    original = MockWorldSeed(
        issue_refinement_backlog=[
            {
                "number": 7101,
                "title": "t",
                "body": "b",
                "labels": [],
                "updated_at": "2026-06-01T00:00:00Z",
            },
        ],
        issue_refinement_verdicts=[
            '{"verdict": "likely_dup", "canonical": 7101, '
            '"evidence": "e", "confidence": "medium"}',
        ],
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.issue_refinement_backlog[0]["number"] == 7101
    assert isinstance(parsed.issue_refinement_backlog[0]["number"], int)
    assert parsed.issue_refinement_verdicts[0].startswith('{"verdict"')


def test_default_seed_has_empty_active_trigger_seams() -> None:
    """#9543 governance active-trigger seed fields default empty (back-compat)."""
    seed = MockWorldSeed()
    assert seed.stale_workspaces == []
    assert seed.gate_activations == []
    assert seed.expired_run_dirs == []


def test_default_seed_has_empty_state_materializer_fields() -> None:
    """#9643 state/JSONL materializer seed fields default empty (back-compat)."""
    seed = MockWorldSeed()
    assert seed.epic_states == []
    assert seed.health_metrics == {}
    assert seed.worker_heartbeats == {}
    assert seed.registered_workers == {}


def test_seed_round_trips_state_materializer_fields_through_json() -> None:
    """The #9643 materializer payloads survive JSON transfer intact.

    All three fields are JSON-native (list-of-dict / string-keyed dicts —
    worker names and artifact names are strings on both sides of the wire),
    so no ``from_json`` coercion is required; the equality check guards a
    future shape that would need it. Ages are RELATIVE offsets
    (``last_activity_age_days`` / ``age_seconds``) so seeds stay
    time-independent — the materializer, not the seed, mints timestamps.
    """
    original = MockWorldSeed(
        epic_states=[
            {
                "epic_number": 7601,
                "title": "Epic: long-forgotten rollup",
                "last_activity_age_days": 3650,
                "child_issues": [],
            },
        ],
        health_metrics={
            "outcomes": [{"outcome": "failure"}, {"outcome": "success"}],
            "item_scores": {"pattern-1": {"score": 0.8, "appearances": 3}},
            "harness_failures": [{"category": "hitl_escalation"}],
        },
        worker_heartbeats={
            "epic_monitor": {
                "status": "running",
                "age_seconds": 7200,
                "details": {"stale_count": 0},
            },
        },
        registered_workers={
            "workspace_gc": {"interval_seconds": 5, "cycle_timeout_seconds": 5},
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.epic_states[0]["epic_number"] == 7601
    assert isinstance(parsed.epic_states[0]["epic_number"], int)
    assert parsed.health_metrics["outcomes"][0] == {"outcome": "failure"}
    assert parsed.worker_heartbeats["epic_monitor"]["age_seconds"] == 7200
    assert parsed.registered_workers["workspace_gc"]["interval_seconds"] == 5


def test_default_seed_has_empty_registered_workers() -> None:
    """#10086 BGWorkerManager registered-loop-set seed field defaults empty."""
    seed = MockWorldSeed()
    assert seed.registered_workers == {}


def test_seed_round_trips_registered_workers_through_json() -> None:
    """Registered-worker entries are JSON-native string-keyed dicts — no
    ``from_json`` coercion is required (#10086)."""
    original = MockWorldSeed(
        registered_workers={
            "workspace_gc": {"interval_seconds": 5, "cycle_timeout_seconds": 5},
            "runs_gc": {},
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.registered_workers["workspace_gc"]["interval_seconds"] == 5
    assert parsed.registered_workers["runs_gc"] == {}


def test_default_seed_has_empty_worker_status_history() -> None:
    """#10133 worker-status event-history seed field defaults empty."""
    seed = MockWorldSeed()
    assert seed.worker_status_history == {}


def test_seed_round_trips_worker_status_history_through_json() -> None:
    """Worker-status history entries are JSON-native string-keyed dicts of
    lists — no ``from_json`` coercion is required (#10133)."""
    original = MockWorldSeed(
        worker_status_history={
            "corpus_learning": [
                {"age_seconds": 82_800, "status": "error", "details": {}},
                {"age_seconds": 3_600, "status": "ok", "details": {"filed": 1}},
            ],
            "rc_budget": [],
        },
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.worker_status_history["corpus_learning"][0]["age_seconds"] == 82_800
    assert parsed.worker_status_history["corpus_learning"][1]["details"] == {"filed": 1}
    assert parsed.worker_status_history["rc_budget"] == []


def test_default_seed_has_empty_repo_wiki_fixtures() -> None:
    """#10133 PIECE 2 repo-wiki-fixture seed field defaults empty."""
    seed = MockWorldSeed()
    assert seed.repo_wiki_fixtures == []


def test_seed_round_trips_repo_wiki_fixtures_through_json() -> None:
    """Repo-wiki fixture entries are JSON-native dicts — no ``from_json``
    coercion is required (#10133 PIECE 2)."""
    original = MockWorldSeed(
        repo_wiki_fixtures=[
            {
                "repo_slug": "acme/widget",
                "title": "Broken cite fixture",
                "content": "See `src/gone.py:vanished` for details.",
                "source_type": "manual",
                "source_issue": 9999,
                "fixed_in_pr": "#9999",
                "code_refs": ["src/gone.py:vanished"],
            }
        ],
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    fixture = parsed.repo_wiki_fixtures[0]
    assert fixture["repo_slug"] == "acme/widget"
    assert fixture["fixed_in_pr"] == "#9999"
    assert fixture["code_refs"] == ["src/gone.py:vanished"]


def test_seed_round_trips_issue_updated_at_through_json() -> None:
    """#9544: a per-issue ``updated_at`` key survives JSON transfer intact.

    ``issues`` entries are plain JSON-native dicts (no ``from_json``
    coercion needed for this key, unlike the outer-key-as-int shapes
    elsewhere in this file) — the equality check guards a future shape
    that would need one.
    """
    original = MockWorldSeed(
        issues=[
            {
                "number": 7701,
                "title": "stale",
                "body": "b",
                "labels": ["hydraflow-hitl"],
                "updated_at": "2020-01-01T00:00:00Z",
            },
            {"number": 7702, "title": "fresh", "body": "b", "labels": []},
        ],
    )

    parsed = MockWorldSeed.from_json(original.to_json())

    assert parsed == original
    assert parsed.issues[0]["updated_at"] == "2020-01-01T00:00:00Z"
    # Absent key round-trips as absent, not a coerced default.
    assert "updated_at" not in parsed.issues[1]


def test_seed_round_trips_active_trigger_seams_through_json() -> None:
    original = MockWorldSeed(
        issues=[
            {
                "number": 7301,
                "title": "done",
                "body": "b",
                "labels": [],
                "state": "closed",
            }
        ],
        prs=[
            {
                "number": 8801,
                "issue_number": 8800,
                "branch": "agent/issue-8800",
                "mergeable": False,
            }
        ],
        stale_workspaces=[{"number": 7301, "branch": "agent/issue-7301"}],
        gate_activations=[
            {
                "name": "mockworld-scenarios",
                "dimension": "tests",
                "required_on": ["main"],
                "workflow": "test.yml",
                "job": "scenario-tests",
                "make_target": "scenario",
            }
        ],
        expired_run_dirs=[{"issue": 7501, "age_days": 3650}],
    )

    restored = MockWorldSeed.from_json(original.to_json())

    assert restored == original
    assert restored.issues[0]["state"] == "closed"
    assert restored.prs[0]["mergeable"] is False
    assert restored.stale_workspaces == original.stale_workspaces
    assert restored.gate_activations == original.gate_activations
    assert restored.expired_run_dirs == original.expired_run_dirs
