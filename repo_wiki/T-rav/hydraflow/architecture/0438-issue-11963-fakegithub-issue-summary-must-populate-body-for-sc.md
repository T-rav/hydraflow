---
id: 0438
topic: architecture
source_issue: 11963
source_phase: plan
created_at: 2026-09-01T09:53:18.676827+00:00
status: active
corroborations: 1
---

# FakeGitHub._issue_summary must populate body for scenario tests

In `tests/scenarios/test_memory_backlog_scenario.py`, verify that `FakeGitHub._issue_summary` includes a populated `body` field. If it doesn't, extend the fake across all three layers (Port docstring, `PRManager`, `FakeGitHub`).

- The durable guard matches on body content (mirror relpath, exact title, overflow-line slug).
- A missing `body` makes the scenario pass vacuously — no summary can ever match.

**Why:** The fresh-checkout scenario proves re-filing is prevented, but only if the fake actually exercises the body-matching logic.
