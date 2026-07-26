---
id: 1248
topic: gotchas
source_issue: 10622
source_phase: plan
created_at: 2026-07-26T11:28:44.489433+00:00
status: active
corroborations: 1
---

# emit() must never raise — DiagramLoop calls it via asyncio.to_thread

Keep `emit()` non-failing. The integrity gate runs in `--integrity` mode, not inside `emit()`.

- `DiagramLoop` calls `emit()` through `asyncio.to_thread`
- A raising emit path poisons auto-regen PRs
- `--integrity` is a separate CLI entry, not woven into emit/check

**Why:** Auto-regen PRs run `emit()` headlessly; an exception there blocks regeneration of all arch artifacts, not just the offending one.
