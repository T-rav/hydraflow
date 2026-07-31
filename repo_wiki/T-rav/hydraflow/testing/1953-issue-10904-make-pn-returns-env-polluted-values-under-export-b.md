---
id: 1953
topic: testing
source_issue: 10904
source_phase: plan
created_at: 2026-07-31T10:40:34.520357+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# make -pn returns env-polluted values under export+?= bleed

In guard tests that verify Makefile variable values, parse the Makefile **textually** (join `\`-continuations, extract the assignment) — never invoke `make -pn`. Under the `Makefile:9` `export` + `?=` bleed, `make -pn` reports the inherited environment value (8 paths), not the file's declared value (9 paths). The textual parse sees the true source. Assert exact counts (7 reap, 9 serial) and paths-exist to catch regex misses.

**Why:** `make -pn` resolves variables with environment overrides applied, masking the exact drift the guard exists to catch.
