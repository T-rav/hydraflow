---
id: 0373
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.381866+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Update _emit_trace strings when migrating gh subprocess to a Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
