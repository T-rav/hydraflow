---
id: 2165
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.584046+00:00
status: superseded
corroborations: 1
supersedes: 2049
superseded_by: 2281
---

# Agent-asset roots force full suite, not dependent mapping

In `scripts/impacted_tests.py`, changes under `.claude/`, `.codex/`, `.pi/` must force the full suite via `_hard_full_suite_reason` — never a hand-listed asset→dependent table.

Example: `AGENT_ASSET_ROOTS = (".claude/", ".codex/", ".pi/")` with a prefix branch. These assets have no `test_<stem>` convention; dependents span ≥6 modules.

**Why:** Filesystem-mirroring lists rot silently; full-suite preserves the "when unsure, run everything" invariant.
