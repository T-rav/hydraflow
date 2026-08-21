---
id: 0307
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-21T11:38:32.622499+00:00
status: active
corroborations: 1
supersedes: 0290
---

# Re-export leaf utilities through phase_utils for regression pin compatibility

When a zero-dependency leaf module owns a predicate that regression tests import from `src/phase_utils.py`, re-export it from `phase_utils.py` with `# noqa: F401` so the pin resolves.

Example: `src/issue_state.py` owns `issue_state_is_resolved`; re-export from `src/phase_utils.py` so the test pin's import statement resolves.

**Why:** The regression test imports from `phase_utils` by name; moving the definition to a leaf without re-exporting breaks the pin's import statement.
