---
id: 0351
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:02:32.378938+00:00
status: superseded
corroborations: 1
supersedes: 0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347
superseded_by: 0370
---

# Update _emit_trace strings when migrating gh subprocess to a Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
