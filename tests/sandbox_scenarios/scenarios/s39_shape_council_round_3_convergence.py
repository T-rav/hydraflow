"""s39 — ShapePhase recovery via diversified-persona round-3 council (ADR-0063 W4).

Drives the W4 recovery branch end-to-end: rounds 1 and 2 of the standard
``ExpertCouncil.vote`` return scripted SPLIT verdicts; ``ShapePhase._run_council_vote``
publishes a ``council_diversified_round`` SHAPE_UPDATE event and dispatches
``ExpertCouncil.vote_diversified`` for round 3; the scripted round-3 verdict
is CONSENSUS, so the issue advances past Shape and on to plan+implement+review+merged.

The scripted scenario uses the ``script_shape_council`` FakeLLM hook added in
PR #9038 (per-round verdict map keyed by round number). Without that hook the
only achievable s39 was happy-path-transparent (no split to recover from).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s39_shape_council_round_3_convergence"
DESCRIPTION = (
    "ExpertCouncil: rounds 1 and 2 split, round 3 (diversified) converges → "
    "issue reaches merged with no human escalation."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 3,
                "title": "Add feature Z",
                "body": "Implement feature Z in src/feature_z.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {3: [{"success": True, "task_count": 1}]},
            "implement": {3: [{"success": True, "branch": "hf/issue-3"}]},
            "review": {3: [{"verdict": "approve", "comments": []}]},
        },
        # ADR-0063 W4: drive the council round progression in ShapePhase.
        # Round 1 + Round 2 split → mediator + diversified-persona round 3
        # → consensus. The round counter on ExpertCouncil advances each
        # call so the FakeLLM verdict map is consulted in lockstep with
        # production's round_num increments.
        phase_scripts={
            "shape_council": {
                3: {1: "split", 2: "split", 3: "consensus"},
            },
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    """Verify the issue reaches merged.

    Only a successful round-3 diversified-persona convergence + subsequent
    phases can produce a merged outcome here: without W4, the split-after-
    round-2 path would post a "no consensus" comment and the issue would
    park in Shape.
    """
    _ = page

    def _has_merged(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict) or item.get("issue_number") != 3:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged,
        timeout=90.0,
    )
