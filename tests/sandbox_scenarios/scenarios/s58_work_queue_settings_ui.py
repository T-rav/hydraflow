"""s58 — Work Queue settings UI exposes the queue-discipline dial (#10037).

The sandbox e2e layer for the selectable work-queue strategy. Unit coverage
proves the ordering engine (``tests/test_queue_strategy.py``) and that the store
consults it (``tests/test_issue_store_queue_strategy.py``); the MockWorld
scenario proves priority labels survive GitHub → ``Task.tags`` → dispatch
(``tests/scenarios/test_queue_strategy_scenario.py``). None of them cross the
browser, so without this the operator-facing half of the feature is unvalidated.

That half matters on its own: the strategy is only switchable at runtime because
``settings_registry.SETTINGS`` lists it, and the dropdown's options are derived
from the ``QueueStrategy`` StrEnum rather than hand-written. A break in either
link leaves the factory permanently on whatever the config file happened to say,
with every lower-tier test still green.

Mirrors s53's shape: settings screen only, no pipeline activity.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s58_work_queue_settings_ui"
DESCRIPTION = (
    "System ▸ Settings ▸ Work Queue exposes the queue_strategy dial with all "
    "three disciplines and the per-band weight rows."
)


def seed() -> MockWorldSeed:
    # No pipeline activity needed — this exercises the settings screen only.
    return MockWorldSeed(cycles_to_run=1)


async def assert_outcome(api, page) -> None:
    await page.goto("/")
    await page.click("text=System")
    await page.get_by_text("Settings", exact=True).first.click()

    panel = page.locator("[data-testid='runtime-settings-panel']")
    await panel.wait_for(timeout=15_000)

    # The Work Queue group renders its strategy row (schema-derived).
    strategy = page.locator("[data-testid='setting-queue_strategy']")
    await strategy.wait_for(timeout=15_000)

    # All three disciplines are offered. The choices derive from the
    # QueueStrategy StrEnum, so a missing option means that discipline is
    # unreachable from the UI — in particular 'fifo', which is the operator's
    # escape hatch back to the pre-#10037 ordering.
    for discipline in ("fifo", "priority", "weighted_mix"):
        options = page.locator(
            "[data-testid='input-queue_strategy'] option", has_text=discipline
        )
        assert await options.count() > 0, (
            f"queue_strategy dropdown is missing the {discipline!r} option"
        )

    # The band weights and the starvation threshold are tunable alongside it.
    # Without these the mix ratio is fixed at its defaults and 'weighted_mix'
    # can't be rebalanced (or its age valve retuned) in the field.
    for field in (
        "queue_weight_p1",
        "queue_weight_p2",
        "queue_weight_unprioritised",
        "queue_starvation_threshold_hours",
    ):
        row = page.locator(f"[data-testid='setting-{field}']")
        await row.wait_for(timeout=10_000)
