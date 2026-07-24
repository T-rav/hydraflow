---
id: 0400
topic: gotchas
source_issue: 10304
source_phase: plan
created_at: 2026-07-24T03:55:27.919605+00:00
status: superseded
corroborations: 1
superseded_by: 0402
---

# `make arch-regen` after ADR edits: commit only if it actually changes output

After amending an ADR body (e.g. `docs/adr/0107-collapse-discover-shape-into-plan.md`), run `make arch-regen` to refresh the generated ADR cross-reference, but only `git add`/commit the regenerated files if they actually diff — a no-op regen left uncommitted is fine, but a stale regenerated artifact left uncommitted after a real change will fail CI drift checks.

**Why:** `docs/arch/generated/` is auto-checked for freshness on every PR (`arch-regen.yml`), so silently skipping this step after a content-changing ADR edit produces a CI failure downstream.
