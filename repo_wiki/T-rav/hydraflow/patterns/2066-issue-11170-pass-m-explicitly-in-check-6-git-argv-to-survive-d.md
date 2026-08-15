---
id: 2066
topic: patterns
source_issue: 11170
source_phase: plan
created_at: 2026-08-14T20:23:54.672666+00:00
status: superseded
corroborations: 1
superseded_by: 2179
---

# Pass -M explicitly in check #6 git argv to survive diff.renames=false

In `scripts/check_console_conformance.py` check #6, always pass `-M` to the `git log`/`git diff` invocation for rename detection. Never rely on the user's `diff.renames` config.

Example: with `diff.renames=false` and no `-M`, a renamed+rewritten ledger record scores `D`+`A` instead of `R091`, so an `M`-only `--diff-filter` misses the move entirely.

**Why:** ARCH-0001's 'corrections are new records' contract becomes bypassable when renames launder verdict flips under non-default git config.
