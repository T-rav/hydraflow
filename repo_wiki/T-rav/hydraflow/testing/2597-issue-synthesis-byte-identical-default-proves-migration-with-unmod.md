---
id: 2597
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:52.069040+00:00
status: active
corroborations: 1
supersedes: 2417
---

# Byte-identical default proves migration with unmodified tests

When introducing a config field to replace scattered string literals, set the default to the exact existing literal. Existing test suites (`tests/test_staging_bisect_loop.py`, `tests/test_auto_agent_preflight*.py`, `tests/test_pr_manager_labels.py`, `tests/test_label_drift_watcher_loop.py`) must stay green unmodified.

Example: renamed-config tests go in a new regression file. Only tests asserting the old literal's mechanics need edits.

**Why:** Unmodified-test-green is the proof that the migration is behavior-preserving under default config; a non-identical default silently changes filed label lists.
