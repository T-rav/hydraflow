---
id: 1366
topic: gotchas
source_issue: 11185
source_phase: review
created_at: 2026-08-15T03:31:43.632068+00:00
status: active
corroborations: 1
---

# escape-ledger.md and erosion-trends.md are runtime-written, not arch-regen

Do not run `make arch-regen` to refresh `docs/arch/generated/escape-ledger.md` or `docs/arch/generated/erosion-trends.md`. `EscapeLedgerLoop` rewrites them each tick and `.gitignore` (lines 275-287) excludes them. CLAUDE.md says `docs/arch/generated/` is "refreshed every PR by arch-regen.yml," but these two files are exceptions, documented in the report renderer's docstring (`src/escape/report.py:3-5`).

**Why:** An agent running `make arch-regen` finds these files unchanged, chases a phantom stale-artifacts CI failure, or hand-edits a loop-owned file.
