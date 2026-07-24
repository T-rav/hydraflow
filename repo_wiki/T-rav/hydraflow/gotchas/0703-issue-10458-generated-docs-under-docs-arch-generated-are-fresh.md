---
id: 0703
topic: gotchas
source_issue: 10458
source_phase: plan
created_at: 2026-07-24T13:01:26.369175+00:00
status: active
corroborations: 1
---

# Generated docs under docs/arch/generated/ are freshness-gated, not just regenerated

Changes to generators like `src/arch/generators/adr_cross_reference.py` require running `make arch-regen` and committing the resulting diff to `docs/arch/generated/adr_xref.md` — CI checks that regeneration produces no further diff ("freshness passes"), so an uncommitted or stale generated file fails the build even though the underlying logic is correct. **Why:** these files are two-writer artifacts (hand-edited generator + machine-regenerated output); skipping the regen step leaves the committed doc out of sync with the generator that CI re-runs.
