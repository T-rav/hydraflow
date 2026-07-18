---
id: 0114
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.463805+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Update _emit_trace command strings when migrating subprocess to Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to reflect the new surface.

- Old: `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]`
- New: `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the actual call path is a Port method.
