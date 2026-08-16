---
id: 1447
topic: gotchas
source_issue: 11335
source_phase: plan
created_at: 2026-08-16T10:56:33.810839+00:00
status: active
corroborations: 1
---

# Fakes and real adapters must share resolution logic via one helper

Rule: when a Fake (e.g., `FakeIssueFetcher`) and its real adapter (e.g., `src/issue_fetcher.py`) resolve the same entity, both must call a single public helper — never duplicate the rule inline.

- `review_branch_candidates(issue_number)` in `src/config.py` is consumed by both `fetch_reviewable_prs` implementations.
- ADR-0047 records this as a testing standard.

**Why:** duplicated logic diverges silently, letting MockWorld scenarios pass green on bugs the real path would catch.
