---
id: 1133
topic: gotchas
source_issue: 10587
source_phase: plan
created_at: 2026-07-26T02:52:52.792480+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# Exempt corroborated fixed_in_pr claims from repo_wiki closed-issue sweep

`active_lint_tracked` in `src/repo_wiki.py` retired tracked wiki entries whenever their `source_issue` closed, even if the entry's `json:entry` block carried a `fixed_in_pr` claim still corroborated by live source (e.g. a `path.py:Symbol` ref that still resolves). Fix: on the `source_issue in closed` branch, check corroboration first — if corroborated, skip the write entirely so the entry stays `active` and never reaches the stale-prune branch. This is complementary, not a full bypass: `wiki_drift_detector` still retires the entry once its `code_refs` die, so dead-code lessons still get swept.
**Why:** without the exemption, durable lessons about shipped fixes get deleted purely because the tracking issue closed, not because the knowledge went stale.
