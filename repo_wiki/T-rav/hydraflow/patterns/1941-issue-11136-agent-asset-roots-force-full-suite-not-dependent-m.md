---
id: 1941
topic: patterns
source_issue: 11136
source_phase: plan
created_at: 2026-08-14T13:02:38.765805+00:00
status: superseded
corroborations: 1
superseded_by: 2049
---

# Agent-asset roots force full suite, not dependent mapping

In `scripts/impacted_tests.py`, changes under `.claude/`, `.codex/`, `.pi/` must force the full suite via `_hard_full_suite_reason`, never a hand-listed asset→dependent table. These assets (`.md`/`.json`/`.sh`) have no `test_<stem>` convention and dependents span ≥6 modules (`tests/test_skill_registry.py`, `tests/test_merge_assets.py`, `tests/regressions/regression_issue_10057.py`). A mapping table mirrors the filesystem and rots on the first test move — the anti-pattern this repo bans. Use `AGENT_ASSET_ROOTS = (".claude/", ".codex/", ".pi/")` with a prefix branch.

**Why:** Filesystem-mirroring lists rot silently; full-suite preserves the "when unsure, run everything" invariant.
