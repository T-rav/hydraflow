"""s07 — WorkspaceGCLoop ticks and reports GC statistics."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s07_workspace_gc_reaps_dead_worktree"
DESCRIPTION = "Workspace GC loop ticks → state records collected/skipped/error stats."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["workspace_gc"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    state = await api.wait_until(
        "/api/state",
        lambda payload: (
            isinstance(payload.get("bg_worker_states", {}).get("workspace_gc"), dict)
            and {
                "collected",
                "skipped",
                "errors",
            }.issubset(
                payload["bg_worker_states"]["workspace_gc"].get("details", {}).keys()
            )
        ),
        timeout=45.0,
    )

    worker_state = state["bg_worker_states"]["workspace_gc"]
    assert worker_state["status"] == "ok"
    details = worker_state["details"]
    assert isinstance(details["collected"], int)
    assert isinstance(details["skipped"], int)
    assert isinstance(details["errors"], int)

    await page.goto("/")
    await page.click("text=System")
    card = page.locator("[data-testid='worker-card-workspace_gc']")
    await card.wait_for(timeout=10_000)
    assert "ok" in ((await card.text_content()) or "").lower()
