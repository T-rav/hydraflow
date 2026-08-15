---
id: 2282
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T01:03:09.941173+00:00
status: superseded
corroborations: 1
supersedes: 2166
superseded_by: 2402
---

# _hard_full_suite_reason ordering precedes .py name-mapping

In `scripts/impacted_tests.py`, `_hard_full_suite_reason` runs before the `.py`-based `test_<stem>` mapping. This ordering is load-bearing: `.codex/skills/**/*.py` correctly hits the agent-asset full-suite trigger rather than falling through to name mapping.

Example: Reordering would cause `.py` files under agent-asset roots to silently bypass the full-suite rule and map to nothing.

**Why:** Reordering would cause `.py` files under agent-asset roots to silently bypass the full-suite rule and map to nothing.
