"""s71 — operator sets a per-loop watchdog-timeout override via the System tab (#9503).

Mirrors s06's shape (click a control on a ``BackgroundWorkerCard`` in the
System ▸ Workers tab, then verify the effect via the dashboard API) for the
watchdog-timeout knob added by #9503. Unit coverage proves
``BGWorkerManager.get_timeout``/``set_timeout`` and the ``timeout_cb`` read
path (``tests/test_bg_worker_manager.py``, ``tests/test_base_background_loop.py``);
the MockWorld scenario proves the override reaches a real loop's watchdog
(``tests/scenarios/test_loop_watchdog_scenario.py``). Neither crosses the
browser or the real dashboard API route, so without this the operator-facing
half of the feature — the actual System-tab control an operator clicks — is
unvalidated.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s73_watchdog_timeout_override_via_ui"
DESCRIPTION = (
    "Operator opens the watchdog editor on a loop-backed worker's System-tab "
    "card, picks a preset, and the override round-trips through "
    "/api/system/workers."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(cycles_to_run=2)


async def assert_outcome(api, page) -> None:
    await page.goto("/")
    await page.click("text=System")

    card = page.locator("[data-testid='worker-card-pr_unsticker']")
    await card.wait_for(timeout=10_000)

    # The watchdog row only renders once the backend has resolved
    # pr_unsticker as loop-backed and watchdog-editable (#9503) — this is the
    # live signal the frontend gates the edit link on, not a client-side
    # allowlist.
    watchdog_row = card.locator("[data-testid='watchdog-pr_unsticker']")
    await watchdog_row.wait_for(timeout=10_000)

    await card.locator("[data-testid='edit-watchdog-pr_unsticker']").click()
    editor = card.locator("[data-testid='watchdog-editor-pr_unsticker']")
    await editor.wait_for(timeout=10_000)

    await editor.locator("[data-testid='watchdog-preset-4h']").click()

    def _has_override(payload: dict) -> bool:
        worker = next(
            (w for w in payload.get("workers", []) if w["name"] == "pr_unsticker"),
            None,
        )
        return worker is not None and worker.get("watchdog_timeout_seconds") == 14400

    state = await api.wait_until("/api/system/workers", _has_override, timeout=30.0)
    worker = next(w for w in state["workers"] if w["name"] == "pr_unsticker")
    assert worker["watchdog_timeout_seconds"] == 14400

    # The editor closes after the pick and the card reflects the new bound —
    # no dangling "close" link left open.
    await card.locator("[data-testid='edit-watchdog-pr_unsticker']").wait_for(
        timeout=10_000
    )
    assert "4h" in await watchdog_row.inner_text()
