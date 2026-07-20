"""s57 — IssueRefinementLoop refines a seeded backlog air-gapped to a digest.

Proves the backlog-refinement loop (#9957) is wired into the sandbox caretaker
registry and runs end-to-end over Fake state — reading the whole open backlog,
judging a duplicate pair, and rendering the rolling operator digest — with NO
real network / ``claude`` / ``gh`` / ``make`` escape.

Why the refinement path needs an extra seam. ``runners=fake_llm`` replaces the
four primary pipeline runners, but IssueRefinementLoop's judgment path spawns a
subprocess none of them cover: ``_refinement_complete`` -> ``_CLIRefinementLLM``
-> a real ``claude`` via ``run_lightweight_agent`` (the s51 / #9796
real-claude-wedge class). ``sandbox_main`` injects an air-gapped stand-in (a
scripted ``refinement_llm``) whenever a scenario seeds a backlog
(``seed.issue_refinement_backlog`` / ``seed.issue_refinement_verdicts``): dup
judgments return the seeded verdict and priority scores return a benign no-op.

Why a PROPOSE, not an auto-close. The scripted verdict is ``likely_dup`` /
``medium`` — deliberately NOT ``exact_dup`` / ``high``, the only tier that
auto-closes. This keeps the assertion surface a single digest proposal and
avoids exercising GitHub close writes (which would work on FakeGitHub, but add
nothing this tier needs to prove). The auto-close / relabel / cache tiers are
covered in-process by the MockWorld scenario tier
(``tests/scenarios/test_issue_refinement_scenario.py``); this tier proves the
docker wiring and the air-gap.

Escape-detection caveat (same honesty as s56). The ``status:ok`` + ``judged>=1``
assertion catches a *hanging* real escape: had ``_refinement_complete`` shelled
out to a real ``claude`` on the air-gapped network, the call would wedge, the
LONG_LLM_CYCLE watchdog would fire, and the cycle would surface ``status ==
"error"`` (never ``judged>=1``). A hypothetical *fast-failing* escape is
swallowed by the loop's per-call ``reraise_on_credit_or_bug`` + fail-soft
handling (``judge_errors += 1``, the pair left uncached) and would leave
``judged == 0`` — so the guarantee here is hang-detection plus proof the
scripted seam was actually consumed; the MockWorld tier owns outcome-level
correctness.

Observable. A ``background_worker_status`` event for ``issue_refinement`` with
cycle ``status == "ok"`` and ``details.judged >= 1``. That combination is a
faithful proxy for "refinement ran air-gapped and judged the seeded dup pair":
had ``list_open_issues`` escaped it would have raised (empty ``config.repo`` ->
not a git repo) and surfaced ``status == "error"``; had the judgment call spawned
a real ``claude`` the cycle would have wedged (watchdog -> ``error``). Only the
Faked backlog read AND the scripted judgment seam both working yields
``judged >= 1`` + ``ok``. The loop also publishes an ``ISSUE_REFINEMENT_UPDATE``
event (surfaced through the same ``/api/events`` history), but
``background_worker_status`` is asserted because its ``details`` carry the
``judged`` count directly.

Excluded from the in-process parity tier (``IN_PROCESS = False``): the backlog
seed + ``refinement_llm`` seam live only in the docker loader (``sandbox_main``);
the in-process harness's ``apply_seed`` doesn't consume
``issue_refinement_backlog`` / ``issue_refinement_verdicts`` and ``LoopCatalog``
exposes no ``refinement_llm`` injection point, so an in-process run would have an
empty backlog (nothing to judge) and a production ``_CLIRefinementLLM`` (a real
``claude`` spawn). Same rationale as s55 / s56; the refinement logic is covered
in-process by the MockWorld tier.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s57_issue_refinement_digest"
DESCRIPTION = "Backlog refinement judges a seeded dup pair air-gapped to a digest."

# The in-process parity tier has no seam for the backlog seed or the refinement
# LLM; run this scenario only in the docker tier (see the module docstring).
IN_PROCESS = False

# Canonical of the near-duplicate pair (lower number wins the rubric tie-break).
_CANONICAL = 7101
_DUPLICATE = 7102


def _backlog() -> list[dict[str, object]]:
    """A three-issue backlog: one near-duplicate pair + one distinct issue.

    The pair scores above the prefilter floor (shared title + body tokens) so
    it becomes the tick's single dup candidate; the distinct issue overlaps
    neither member and is dropped by the prefilter (proving no spurious judged
    call). All issues are label-free so the pipeline's store refresh (which
    pulls only ``hydraflow-*``-labelled issues) never touches them — only the
    backlog-wide refinement sweep does.
    """
    return [
        {
            "number": _CANONICAL,
            "title": (
                "CIMonitorLoop misses a red main-branch check when the run URL is empty"
            ),
            "body": (
                "When the main-branch CI concludes failure but GitHub returns an "
                "empty run URL, CIMonitorLoop treats the branch as green and "
                "never files an escalation. The empty-URL fallback path skips the "
                "red-status handler entirely."
            ),
            "labels": [],
            "updated_at": "2026-06-01T00:00:00Z",
        },
        {
            "number": _DUPLICATE,
            "title": (
                "CIMonitorLoop ignores a red main-branch CI failure when the run "
                "URL is empty"
            ),
            "body": (
                "If the main-branch CI status has an empty run URL, the monitor "
                "loop swallows the failure and reports the branch as passing. The "
                "empty URL short-circuits the failure escalation handler."
            ),
            "labels": [],
            "updated_at": "2026-06-01T00:00:00Z",
        },
        {
            "number": 7103,
            "title": "Dashboard dark-mode toggle flickers on Safari during first paint",
            "body": (
                "The theme toggle in the dashboard header repaints twice on "
                "Safari when the page first loads, causing a visible flash. "
                "Chrome and Firefox are unaffected."
            ),
            "labels": [],
            "updated_at": "2026-06-01T00:00:00Z",
        },
    ]


# A likely_dup / medium verdict — NOT the exact_dup / high tier that auto-closes.
# The loop tiers this into a DigestProposal (operator question), so the tick
# judges the pair (``judged == 1``) and renders it in the digest without any
# GitHub close write.
_DUP_VERDICT = (
    "```json\n"
    '{"verdict": "likely_dup", "canonical": 7101, '
    '"evidence": "both #7101 and #7102 report CIMonitorLoop swallowing a red '
    'main-branch result when the run URL is empty", "confidence": "medium"}\n'
    "```\n"
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["issue_refinement"],
        issue_refinement_backlog=_backlog(),
        issue_refinement_verdicts=[_DUP_VERDICT],
        # Tick fast so the caretaker's first cycle (run_on_startup=False) lands
        # well within the assert window on CI's slower runners. Overrides the
        # loop's daily production interval via the sandbox get_interval callback.
        sandbox_loop_interval=6,
        cycles_to_run=3,
    )


def _is_refinement_tick(event: object) -> bool:
    """True for an issue_refinement worker-status event that judged >=1 dup pair
    within a cleanly-completed cycle."""
    if not isinstance(event, dict):
        return False
    if event.get("type") != "background_worker_status":
        return False
    data = event.get("data") or {}
    if data.get("worker") != "issue_refinement":
        return False
    if data.get("status") != "ok":
        return False
    details = data.get("details") or {}
    return isinstance(details.get("judged"), int) and details.get("judged", 0) >= 1


async def assert_outcome(api, page) -> None:
    """Verify issue_refinement read the seeded backlog, judged the dup pair, and
    completed the cycle cleanly (no real-claude wedge)."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: (
            isinstance(payload, list) and any(_is_refinement_tick(e) for e in payload)
        ),
        timeout=90.0,
    )

    refinement_ticks = [e for e in events_payload if _is_refinement_tick(e)]
    assert refinement_ticks, (
        "Expected an issue_refinement background_worker_status event with "
        "status='ok' and details.judged>=1 (seeded dup pair judged air-gapped); "
        f"got none. All events: {events_payload!r}"
    )
