---
id: 0297
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:12:52.209426+00:00
status: active
corroborations: 1
supersedes: 0288,0289,0290,0291,0292,0293
---

# Update _emit_trace strings when migrating gh subprocess to a Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
