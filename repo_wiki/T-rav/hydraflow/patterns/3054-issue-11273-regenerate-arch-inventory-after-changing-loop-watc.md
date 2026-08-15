---
id: 3054
topic: patterns
source_issue: 11273
source_phase: plan
created_at: 2026-08-15T20:41:55.284238+00:00
status: active
corroborations: 1
---

# Regenerate arch inventory after changing loop watchdog class

After changing a loop's watchdog class (e.g., adding `LONG_LLM_CYCLE`), run `make arch-regen` and commit only the regenerated file. `docs/arch/generated/ai_system_inventory.md` tracks the watchdog class per loop row — the `diagnostic` row flips from `—` to the LLM bound. Full `make quality` must pass, not a subset.

**Why:** Unrelated generated-artifact drift in `git status` signals stale or uncommitted regeneration; the cleanup blast-radius rule requires a clean full-quality run.
