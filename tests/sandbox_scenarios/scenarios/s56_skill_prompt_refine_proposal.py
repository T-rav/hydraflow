"""s56 — SkillPromptEvalLoop's drift-triggered self-refinement runs air-gapped.

Proves the prompt self-refinement pipeline (#9724) is wired into the sandbox
caretaker registry and runs end-to-end over Fake state, with NO real
network / ``claude`` / ``gh`` / ``make`` escape.

Why the refine path needs an extra seam. ``runners=fake_llm`` replaces the four
primary pipeline runners, but SkillPromptEvalLoop's refine path spawns two
subprocesses it does NOT cover:

* ``_run_corpus`` → ``make trust-adversarial FORMAT=json`` (the weekly backstop);
* ``_refine_llm_complete`` → a real ``claude`` via ``run_lightweight_agent``
  (the s51 / #9796 real-claude-wedge class).

``sandbox_main`` injects air-gapped stand-ins for both when a scenario scripts a
corpus regression (``seed.skill_prompt_corpus_cases`` /
``seed.skill_prompt_refine_patch``): ``_run_corpus`` returns the seeded PASS→FAIL
case and the refine LLM returns the seeded patch.

Escape-detection caveat: the ``status:ok`` assertion catches a *hanging* real
escape (the established real-claude-in-air-gap failure mode — watchdog fires,
status flips to ``error``). A hypothetical *fast-failing* escape is swallowed by
``_try_refine``'s soft-failure handling and would leave ``status:ok`` — the
guarantee here is hang-detection; the MockWorld tier owns outcome-level checks.

Why a tripwire outcome, not a green PR. A *green* refine PR is not achievable
air-gapped: ``_open_refine_pr`` runs a live ``corpus_runner`` validation
subprocess (real LLM) and opens the PR through ``generate_and_open_pr_async``,
which shells out to raw ``git`` / ``gh`` (no Fake seam). So the seeded patch is
crafted to touch a corpus path — tripping ``check_tripwires`` — so the loop
exercises the whole synthesis → parse → safety-gate chain and returns the
``tripwire`` outcome BEFORE ever reaching ``_open_refine_pr``. The refine LOGIC
(green / red / cap paths) is covered in-process by the MockWorld tier
(``tests/scenarios/test_skill_prompt_refine_scenario.py``); this tier proves the
docker wiring and the air-gap.

Observable. A ``background_worker_status`` event for ``skill_prompt_eval`` with
cycle status ``ok`` and ``details.filed >= 1``. That combination is a faithful
proxy for "refine ran air-gapped to a clean tripwire": had ``_run_corpus``
shelled out to ``make`` it would have returned an empty corpus (``no_cases``,
``filed == 0``); had the refine LLM spawned a real ``claude`` the cycle would
have wedged and surfaced ``status == "error"`` (watchdog timeout). Only both
seams working AND the refine path completing yields ``filed >= 1`` + ``ok``.

Excluded from the in-process parity tier (``IN_PROCESS = False``): the two seams
live only in the docker loader (``sandbox_main``); the in-process harness builds
the loop via ``LoopCatalog`` with no seam, so its ``_run_corpus`` would no-op
(the tmp repo has no Makefile → empty corpus → ``no_cases``) and exercise
nothing. Same rationale as s55.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s56_skill_prompt_refine_proposal"
DESCRIPTION = "Drift-triggered prompt self-refinement runs air-gapped to a tripwire."

# The in-process parity tier has no seam for the refine subprocesses; run this
# scenario only in the docker tier (see the module docstring).
IN_PROCESS = False

_CASE_ID = "s56-refine-regressed-case"
# Must be a key of prompt_refiner.SKILL_BUILDER_MODULES so refine gets past the
# "no builder module registered" guard and into context assembly / synthesis.
_SKILL = "diff-sanity"

# A refine LLM response whose ```diff fence targets the adversarial corpus
# itself (``tests/trust/**`` is off-limits). ``check_tripwires`` rejects it with
# "patch edits the corpus itself", so ``_compute_refine_outcome`` returns
# ``tripwire`` before any worktree/validation/PR work runs.
_TRIPWIRE_PATCH = (
    "```diff\n"
    "--- a/tests/trust/adversarial/corpus_runner.py\n"
    "+++ b/tests/trust/adversarial/corpus_runner.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-CORPUS_RUNNER_UNTOUCHED\n"
    "+CORPUS_RUNNER_TAMPERED\n"
    "```\n"
)


def _regressed_case() -> dict[str, object]:
    return {
        "case_id": _CASE_ID,
        "skill": _SKILL,
        "expected_catcher": _SKILL,
        "status": "FAIL",
        "provenance": "hand-crafted",
        "summary": "the skill stopped catching this adversarial case",
    }


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["skill_prompt_eval"],
        skill_prompt_corpus_cases=[_regressed_case()],
        skill_prompt_refine_patch=_TRIPWIRE_PATCH,
        # Tick fast so the caretaker's first cycle (run_on_startup=False) lands
        # well within the assert window on CI's slower runners.
        sandbox_loop_interval=6,
        cycles_to_run=3,
    )


def _is_refine_tick(event: object) -> bool:
    """True for a skill_prompt_eval worker-status event that filed a drift +
    ran refine within a cleanly-completed cycle."""
    if not isinstance(event, dict):
        return False
    if event.get("type") != "background_worker_status":
        return False
    data = event.get("data") or {}
    if data.get("worker") != "skill_prompt_eval":
        return False
    if data.get("status") != "ok":
        return False
    details = data.get("details") or {}
    return isinstance(details.get("filed"), int) and details.get("filed", 0) >= 1


async def assert_outcome(api, page) -> None:
    """Verify skill_prompt_eval detected the seeded regression, filed a drift
    issue, and drove refine to a clean air-gapped tripwire (no wedge)."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: (
            isinstance(payload, list) and any(_is_refine_tick(e) for e in payload)
        ),
        timeout=90.0,
    )

    refine_ticks = [e for e in events_payload if _is_refine_tick(e)]
    assert refine_ticks, (
        "Expected a skill_prompt_eval background_worker_status event with "
        "status='ok' and details.filed>=1 (drift filed + refine attempted "
        f"air-gapped); got none. All events: {events_payload!r}"
    )
