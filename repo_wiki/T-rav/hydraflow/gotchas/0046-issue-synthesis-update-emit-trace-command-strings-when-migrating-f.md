---
id: 0046
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:59:29.446728+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Update _emit_trace command strings when migrating from subprocess to Port calls

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to reflect the new surface.

- Old: `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]`
- New: `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the actual call path is a Port method.
