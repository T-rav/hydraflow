"""s82 — full machine: standard PR path AND the RC promotion path in one run.

The post-merge smoke (#10309). One boot of the real server exercises both
merge lanes of ADR-0042's two-tier branch model:

1. Standard PR path — a ``hydraflow-ready`` issue rides the full assembly
   line (triage → plan → implement → review → merge), same as s01.
2. RC promotion path — ``staging_enabled`` is seeded true, so
   StagingPromotionLoop runs its real cadence: tick 1 cuts an ``rc/*``
   branch and opens a promotion PR (first boot has no cadence marker →
   cut immediately); tick 2 finds that PR via FakeGitHub's upgraded
   promotion read side, sees green CI, and merges it to main.

Observables:
- API: /api/issues/history reports issue 1 merged (standard path).
- Events: a staging_promotion BACKGROUND_WORKER_STATUS event with
  ``details.status == "promoted"`` — the loop's own _do_work result against
  FakeGitHub, so this is the authoritative proof the RC was cut, found,
  CI-green, and merged. (The /api/staging-promotion/status route can't serve
  this: the dashboard wires a real PRManager that's blind to FakeGitHub on
  the air-gapped network — its recent_promoted always reads 0.)
- API: /api/staging-promotion/status confirms the config→disk half —
  enabled + a recorded RC cut (read from .staging_promotion_last_rc, no gh).
- UI: Outcomes row for issue 1 + MOCKWORLD banner.

Runs on every push to staging/main via the post-merge-smoke CI job, so a
merge that breaks either lane is caught within minutes, not at the next
PR gate or nightly.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s82_full_machine_rc_promotion"
DESCRIPTION = (
    "Post-merge smoke: issue → merged (standard path) AND StagingPromotionLoop "
    "cuts rc/* → promotes to main, in one boot."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 1,
                "title": "Add hello world",
                "body": "Implement a hello-world function in src/hello.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan": {1: [{"success": True, "task_count": 1}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "review": {1: [{"verdict": "approve", "comments": []}]},
        },
        # The promotion loop needs two ticks (cut, then find+merge); a 10s
        # interval keeps tick 2 well inside the assertion windows below.
        sandbox_loop_interval=10,
        cycles_to_run=6,
        staging_enabled=True,
    )


async def assert_outcome(api, page) -> None:
    """Both merge lanes must land: the issue PR and the RC promotion PR."""

    # --- Standard PR path (s01's assertion) ---
    def _has_merged_issue_1(payload: dict) -> bool:
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("issue_number") != 1:
                continue
            outcome = item.get("outcome") or {}
            if isinstance(outcome, dict) and outcome.get("outcome") == "merged":
                return True
        return False

    await api.wait_until(
        "/api/issues/history?limit=500",
        _has_merged_issue_1,
        timeout=60.0,
    )

    # --- RC promotion path ---
    # The merge-proof comes from the loop's own worker-status EVENT, not the
    # /api/staging-promotion/status route: that route resolves the dashboard's
    # real PRManager (dashboard.py builds ``PRManager(config, ...)``), which on
    # the air-gapped network can't see FakeGitHub's promotion state — its
    # recent_promoted always reads 0. The BACKGROUND_WORKER_STATUS event, by
    # contrast, carries the loop's own _do_work return dict against FakeGitHub,
    # so details.status == "promoted" proves cut → find → CI-green → merge
    # completed end-to-end (this is the observable s20 uses for rc_budget too).
    def _has_promoted_event(payload: list) -> bool:
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "staging_promotion"
            and e.get("data", {}).get("details", {}).get("status") == "promoted"
            for e in (payload if isinstance(payload, list) else [])
        )

    await api.wait_until("/api/events", _has_promoted_event, timeout=90.0)

    # The status route still confirms the config→disk wiring: staging enabled
    # and the loop recorded its RC cut on disk (.staging_promotion_last_rc,
    # read by the route without touching gh). recent_promoted is intentionally
    # NOT asserted here — see the comment above on the real-PRManager gap.
    status = await api.wait_until(
        "/api/staging-promotion/status",
        lambda p: (
            isinstance(p, dict)
            and p.get("enabled") is True
            and bool(p.get("last_rc_cut_at"))
        ),
        timeout=30.0,
    )
    assert status.get("enabled") is True, f"staging not enabled: {status!r}"
    assert status.get("last_rc_cut_at"), f"no RC cut recorded: {status!r}"

    # --- UI: Outcomes row renders + MOCKWORLD banner visible (s01's checks) ---
    await page.goto("/")
    await page.click("text=Outcomes")
    await page.wait_for_selector("[data-testid='outcome-row-1']", timeout=10_000)
    text = await page.locator("[data-testid='outcome-row-1']").text_content()
    assert "merged" in (text or "").lower(), f"got {text!r}"

    banner = page.locator("[data-testid='mockworld-banner']")
    assert await banner.is_visible()
