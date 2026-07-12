"""s53 — Model-Routing settings UI renders the provider dials + key-status badge.

Guards the schema-driven Settings ▸ Model Routing screen end-to-end: every
one-shot role's provider dropdown must offer the ``zai`` backend (Literal-derived
enum choices), and each ``<provider>_base_url`` row must carry the key-status
badge (booleans-only; no key in the sandbox → "not set"). This is the sandbox
e2e layer for the pluggable-provider UI (unit coverage: RuntimeSettingsPanel
vitest; API coverage: test_control_routes_settings). Without it the dropdown +
badge wiring is validated only below the browser layer.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s53_model_routing_settings_ui"
DESCRIPTION = (
    "System ▸ Settings ▸ Model Routing exposes the zai provider option in every "
    "one-shot role dropdown and a key-status badge (no key → 'not set')."
)


def seed() -> MockWorldSeed:
    # No pipeline activity needed — this exercises the settings screen only.
    return MockWorldSeed(cycles_to_run=1)


async def assert_outcome(api, page) -> None:
    await page.goto("/")
    await page.click("text=System")
    # Open the Settings sub-tab (schema-driven RuntimeSettingsPanel).
    await page.get_by_text("Settings", exact=True).first.click()

    panel = page.locator("[data-testid='runtime-settings-panel']")
    await panel.wait_for(timeout=15_000)
    # The Model Routing group renders its base-URL row (schema-derived).
    await page.locator("[data-testid='setting-zai_base_url']").wait_for(timeout=15_000)

    # Every one-shot role's provider dropdown offers the "zai" backend — the
    # choices derive from the config Literal, so a missing option means the
    # dial can't be pointed at z.ai from the UI.
    for field in (
        "wiki_compilation_provider",
        "adr_review_provider",
        "transcript_summary_provider",
        "triage_honeypot_provider",
        "pr_unstick_provider",
        "term_proposer_provider",
    ):
        options = page.locator(f"[data-testid='input-{field}'] option", has_text="zai")
        assert await options.count() > 0, (
            f"{field} dropdown is missing the 'zai' option"
        )

    # The key-status badge renders. No provider key is set in the sandbox, so it
    # must read "not set" (booleans only — the secret value never reaches the UI).
    badge = page.locator("[data-testid='keystatus-zai_base_url']")
    await badge.wait_for(timeout=10_000)
    badge_text = await badge.inner_text()
    assert "not set" in badge_text.lower(), (
        f"expected the zai key-status badge to read 'not set' (no key in sandbox), "
        f"got {badge_text!r}"
    )
