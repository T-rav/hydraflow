"""s06 — operator toggles loop off via System tab; loop stops ticking."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s06_kill_switch_via_ui"
DESCRIPTION = (
    "Toggle loop off in System tab → ADR-0049 in-body gate fires; no further ticks."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(cycles_to_run=4)


async def assert_outcome(api, page) -> None:
    await page.goto("/")
    await page.click("text=System")

    card = page.locator("[data-testid='worker-card-dependabot_merge']")
    await card.wait_for(timeout=10_000)
    await card.get_by_role("button", name="On").click()

    state = await api.wait_until(
        "/api/state",
        lambda payload: "dependabot_merge" in payload.get("disabled_workers", []),
        timeout=30.0,
    )
    assert "dependabot_merge" in state["disabled_workers"]

    await card.get_by_role("button", name="Off").wait_for(timeout=10_000)
