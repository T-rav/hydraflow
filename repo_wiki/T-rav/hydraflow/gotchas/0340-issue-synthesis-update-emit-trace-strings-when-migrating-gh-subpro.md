---
id: 0340
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.505679+00:00
status: active
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
---

# Update _emit_trace strings when migrating gh subprocess to a Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
