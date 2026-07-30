---
id: 1187
topic: gotchas
source_issue: 10754
source_phase: plan
created_at: 2026-07-27T23:21:47.785784+00:00
status: active
corroborations: 1
---

# Closing PR may not ship requested work; verify against issue intent

A merged PR that references an issue number does not prove the requested work shipped — diff the PR against the issue's acceptance criteria before treating the gap as resolved.

Example: PR #10693 closed #10655 with an unrelated `fixed_in_pr` dedup fix in `src/wiki_compiler.py`; the completeness check #10655 asked for was never built, leaving `plan_topic_repair`'s 471 live `left_on_primary` predecessors unverified.

**Why:** Relying on issue-closed status alone lets phantom tools and missing auditors persist in the live wiki indefinitely.
