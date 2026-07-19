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
