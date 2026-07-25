---
id: 1014
topic: testing
source_issue: 10515
source_phase: plan
created_at: 2026-07-25T05:40:37.556722+00:00
status: active
corroborations: 1
---

# Blast-radius check for FakeIssueStore edits: dashboard + scenario tests

Changes to `src/mockworld/fakes/fake_issue_store.py` bucket logic should be verified with `pytest tests/test_fake_issue_store.py tests/test_issue_store.py tests/test_dashboard_routes_state.py tests/scenarios/ -q` before `make quality`, since the Fake backs dashboard snapshot routes and multiple MockWorld scenarios beyond the one being added. A targeted single-file pytest run is not sufficient proof per the code-cleanup gotcha in the project's global CLAUDE.md (PR #8460 precedent).

**Why:** The Fake is shared infrastructure — a bucket-status change can silently break dashboard route tests or unrelated scenarios that assert on the same snapshot shape.
