---
id: 0310
topic: architecture
source_issue: 11110
source_phase: plan
created_at: 2026-08-14T08:05:02.917612+00:00
status: active
corroborations: 1
---

# paths-filter entries are load-bearing gate surfaces

Adding `agents/**` to the `arch` paths-filter in `ci.yml` is as load-bearing as the `make console-conformance` step itself. If `agents/**` is missing from the filter, an agents-only PR skips the Architecture Check job entirely, and a record edit merges unchecked.

Treat paths-filter changes as part of the enforcement surface, not cosmetic CI config.

**Why:** A skipped job is indistinguishable from a passing job in the CI Gate's `needs` graph — the gate stays green while the check never ran.
