---
id: 0320
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.194456+00:00
status: active
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
---

# Update _emit_trace strings when migrating gh subprocess to a Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
