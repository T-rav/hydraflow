"""s92 — #11298 light lane, single spawn: a triage-scored simple issue skips
the staged plan/implement pipeline and takes ONE auto-agent spawn to a PR.

Flow (the lane is ON by default since PR #11590):

- #1 is seeded at ``hydraflow-find``; the scripted triage returns ``ready``
  with ``complexity_score=2`` (≤ ``auto_agent_light_max_complexity``, default
  3), which TriagePhase records in the issue cache.
- PlanPhase's ``_route_light_lane`` reads that score and swaps the claim label
  (``hydraflow-auto-light``) instead of planning — no planner spawn, no
  adversarial plan review, no implement phase.
- AutoAgentPreflightLoop polls the claim label and spawns the single-session
  auto-agent. In the sandbox that spawn is the seed-scripted fake
  (``scripts["auto_agent"]``, rebound by ``air_gap_runner_sentinels``):
  ``AutoAgentRunner`` is constructed INSIDE ``_build_spawn_fn`` — not
  injected — so without the rebinding the loop spawns a REAL ``claude`` in the
  air-gapped container (``Agent CLI authentication failed`` retries, the wedge
  that turned s54 red once decomposed children started routing to the lane).
  The fake mints the PR through the PRPort on ``agent/auto-agent-1`` and
  reports ``resolved``.
- ``apply_decision`` releases the claim to ``hydraflow-review``; the review
  stage discovers the PR by issue number, the scripted review approves, the PR
  merges and the outcome is recorded.

Asserts via REST:
- ``/api/state``: the auto-agent attempt counter for #1 is EXACTLY 1. Only
  AutoAgentPreflightLoop bumps that counter and #1 never carried an
  escalation label, so one attempt == the light lane (not the staged path)
  handled the issue, with a single spawn.
- ``/api/issues/history``: #1 reached ``merged`` with a PR number on its
  outcome — the PR the spawn minted is the one that landed.
- ``/api/pipeline``: #1 is not in the HITL stage (no ``human-required``
  hand-off).
UI: the Outcomes tab renders the merged row for #1.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s92_light_lane_single_spawn"
DESCRIPTION = (
    "Complexity-2 issue routes to the auto-agent light lane: one scripted "
    "spawn mints the PR, the claim releases to review, the PR merges — no "
    "plan/implement stage, no human hand-off."
)

_ISSUE = 1


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": _ISSUE,
                "title": "Fix typo in operator panel label",
                "body": "One-line copy fix in the operator panel header.",
                "labels": ["hydraflow-find"],
            }
        ],
        scripts={
            # ready + complexity 2: clears the discovery gate (default
            # clarity_score=10) and sits under auto_agent_light_max_complexity
            # (3), so PlanPhase routes it to the lane instead of planning.
            "triage": {_ISSUE: [{"ready": True, "complexity_score": 2}]},
            # The single-session spawn outcome the sandbox's fake spawn seam
            # pops (FakeLLM.next_auto_agent_spawn). ``resolved`` with no
            # explicit pr_url mints the PR through the PRPort so the review
            # stage discovers it exactly as it would a real one.
            "auto_agent": {
                _ISSUE: [
                    {"status": "resolved", "diagnosis": "Copy fixed; tests green."}
                ]
            },
            "review": {_ISSUE: [{"verdict": "approve", "comments": []}]},
        },
        # loops_enabled=None: every caretaker runs — including
        # auto_agent_preflight, the lane's consumer — and the phase
        # orchestrators run regardless (separate BGWorkerManager gate).
        loops_enabled=None,
        # Used by the Tier-1 parity check (single-shot run_pipeline; the
        # harness PlanPhase has no issue cache, so the issue plans on the
        # staged path there and merely has to show progress past triage).
        cycles_to_run=4,
        # AutoAgentPreflightLoop has run_on_startup=False, so its first tick
        # lands one caretaker interval after boot; tick every 15s (not the
        # 60s default) so claim → spawn → review → merge completes well inside
        # the assertion window on slow CI runners.
        sandbox_loop_interval=15,
    )


def _auto_agent_attempts(state: dict) -> int:
    ledgers = state.get("convergence_ledgers") if isinstance(state, dict) else None
    ledger = (ledgers or {}).get(str(_ISSUE)) or {}
    stage = (ledger.get("stage_state") or {}).get("auto_agent") or {}
    try:
        return int(stage.get("attempts", 0))
    except (TypeError, ValueError):
        return 0


def _merged_outcome(payload: dict) -> dict | None:
    items = payload.get("items") if isinstance(payload, dict) else None
    for item in items or []:
        if isinstance(item, dict) and item.get("issue_number") == _ISSUE:
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return outcome
    return None


async def assert_outcome(api, page) -> None:
    # 1. The fake spawn ran: the attempt counter only the preflight loop bumps
    #    went from 0 to 1 (claim label → spawn).
    await api.wait_until(
        "/api/state",
        lambda payload: _auto_agent_attempts(payload) >= 1,
        timeout=150.0,
    )

    # 2. The PR the spawn minted went through review and merged — the same
    #    IssueHistoryEntry payload the Outcomes UI consumes (as in s01).
    history = await api.wait_until(
        "/api/issues/history?limit=500",
        lambda payload: _merged_outcome(payload) is not None,
        timeout=150.0,
    )
    outcome = _merged_outcome(history)
    assert outcome is not None, f"issue #{_ISSUE} never merged: {history!r}"
    assert isinstance(outcome.get("pr_number"), int) and outcome["pr_number"] > 0, (
        f"merged outcome carries no PR number (no PR existed?): {outcome!r}"
    )

    # 3. Exactly ONE spawn, re-read after the merge so a late re-poll of the
    #    claim label (crash-recovery path) would be visible as a second bump.
    state = await api.get("/api/state")
    attempts = _auto_agent_attempts(state)
    assert attempts == 1, f"expected exactly one light-lane spawn, saw {attempts}"

    # 4. No human hand-off: the issue never entered the HITL stage.
    pipeline = await api.get("/api/pipeline")
    hitl = (pipeline.get("stages") or {}).get("hitl") or []
    assert all(entry.get("issue_number") != _ISSUE for entry in hitl), (
        f"issue #{_ISSUE} unexpectedly in the HITL stage: {hitl!r}"
    )

    # UI: the Outcomes tab renders the merged row for #1.
    await page.goto("/")
    await page.click("text=Outcomes")
    await page.wait_for_selector(
        f"[data-testid='outcome-row-{_ISSUE}']", timeout=10_000
    )
    text = await page.locator(f"[data-testid='outcome-row-{_ISSUE}']").text_content()
    assert "merged" in (text or "").lower(), f"got {text!r}"
