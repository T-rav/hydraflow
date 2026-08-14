---
id: 2049
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.839345+00:00
status: superseded
corroborations: 1
supersedes: 1941
superseded_by: 2165
---

# Agent-asset roots force full suite, not dependent mapping

In `scripts/impacted_tests.py`, changes under `.claude/`, `.codex/`, `.pi/` must force the full suite via `_hard_full_suite_reason` — never a hand-listed asset→dependent table.

Example: `AGENT_ASSET_ROOTS = (".claude/", ".codex/", ".pi/")` with a prefix branch. These assets have no `test_<stem>` convention; dependents span ≥6 modules (`tests/test_skill_registry.py`, `tests/test_merge_assets.py`).

**Why:** Filesystem-mirroring lists rot silently; full-suite preserves the "when unsure, run everything" invariant.
