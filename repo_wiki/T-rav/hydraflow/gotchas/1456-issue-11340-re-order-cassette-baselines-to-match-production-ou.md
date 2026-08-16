---
id: 1456
topic: gotchas
source_issue: 11340
source_phase: plan
created_at: 2026-08-16T11:56:57.838118+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Re-order cassette baselines to match production output order

When fixing fake ordering, also re-order hand-authored cassette baselines to newest-first so they match both the corrected fake and real `gh`.

- `tests/trust/contracts/cassettes/github/issue_list_open.yaml` was pinned #101 before #102; re-order to newest-first, keep `baseline_only: true`.
- Run `pytest tests/scenarios tests/trust/contracts -q` explicitly — scenario tests that silently relied on insertion order will surface.

**Why:** A cassette pinned to insertion order fails against the corrected fake; scenario tests with hidden insertion-order dependencies are the real gate for ordering changes.
