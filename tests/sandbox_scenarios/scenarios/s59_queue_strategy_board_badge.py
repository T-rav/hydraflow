"""s59 — the work-queue strategy badge renders on the board (#10067).

The sandbox e2e layer for the strategy visualisation. It proves the one wiring
path only a real browser can exercise: the active ``queue_strategy`` travels
``HydraFlowConfig`` → ``ControlStatusConfig`` → ``GET /api/control/status`` →
the React context ``config`` → the ``StreamView`` Pipeline Flow badge. A break
anywhere on that chain (a missing DTO field, a dropped context key, a render
guard) leaves the operator with no at-a-glance signal of which algorithm is
picking work — the exact gap this feature closes.

Deliberately scoped to the badge, which renders on board load independent of
queue timing, so the scenario is deterministic. The other two visual pieces are
proven where they can be asserted without a live-pipeline race:

* priority chips + dispatch-order sort — vitest
  (``StreamCard.test.jsx`` / ``StreamView.test.jsx``); and
* the snapshot payload carrying priority + dispatch_rank — the unit and
  MockWorld tiers (``test_issue_store_snapshot_priority.py`` /
  ``test_queue_viz_snapshot_scenario.py``).

Seeding a queued issue and asserting its chip through the board would reintroduce
a dispatch-timing race (the very class of flake #9925 cost days on), so it is
left to those deterministic tiers.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s59_queue_strategy_board_badge"
DESCRIPTION = (
    "The Work Stream board shows the active work-queue strategy badge, proving "
    "queue_strategy reaches the browser via /api/control/status."
)


def seed() -> MockWorldSeed:
    # The board (Work Stream tab) is the default view; no pipeline activity is
    # needed — the badge reads the active strategy from config, not the queue.
    return MockWorldSeed(cycles_to_run=1)


async def assert_outcome(api, page) -> None:
    await page.goto("/")

    # The board is the default tab; the Pipeline Flow header carries the badge.
    flow = page.locator("[data-testid='pipeline-flow']")
    await flow.wait_for(timeout=15_000)

    badge = page.locator("[data-testid='queue-strategy-badge']")
    await badge.wait_for(timeout=15_000)

    # It must name a real discipline, not render empty — the whole point is that
    # a glance tells the operator which algorithm is active.
    text = (await badge.inner_text()).lower()
    assert any(name in text for name in ("weighted", "priority", "fifo")), (
        f"strategy badge should name the active discipline, got {text!r}"
    )
