---
id: 2201
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.454237+00:00
status: superseded
corroborations: 1
supersedes: 2072
superseded_by: 2230
---

# Parse both sides at runtime in drift-guard tests

A drift guard that hardcodes the expected path list becomes the Nth copy and drifts silently. Parse both sides at runtime — `yaml.safe_load` for workflow YAML, textual regex for `Makefile` assignments — and assert bidirectional set equality.

Example: The only acceptable hardcoded constant is a documented *delta* between related sets (e.g. `REAP_TESTS` vs `linux-signal-smoke`: 7 vs 6, differing by `test_auto_pr_preflight_gate.py`).

**Why:** Hardcoding the list makes the guard a participant in the drift it should detect.
