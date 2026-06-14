---
id: 0013
topic: gotchas
source_issue: 9442
source_phase: review
created_at: 2026-06-13T07:10:55.323956+00:00
status: active
corroborations: 1
---

# Update _emit_trace command strings when migrating from subprocess to Port calls

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to reflect the new surface.

- Old surface: `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]`
- New surface: `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`

The stale string means traces show a subprocess invocation for an operation that never spawns a process.

**Why:** Observability consumers (dashboards, alerts, postmortems) rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the actual call path is a Port method.
