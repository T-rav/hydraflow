---
id: 2909
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.438738+00:00
status: active
corroborations: 1
supersedes: 2780
---

# Pass -M explicitly in check #6 git argv to survive diff.renames=false

In `scripts/check_console_conformance.py` check #6, always pass `-M` to the `git log`/`git diff` invocation for rename detection. Never rely on the user's `diff.renames` config.

Example: with `diff.renames=false` and no `-M`, a renamed+rewritten ledger record scores `D`+`A` instead of `R091`, so an `M`-only `--diff-filter` misses the move entirely. See also: [patterns] — Immutability check needs merge-base range; [patterns] — Widen check #6 --diff-filter to DMR.

**Why:** ARCH-0001's 'corrections are new records' contract becomes bypassable when renames launder verdict flips under non-default git config.
