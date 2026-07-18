---
id: 0080
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.515292+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Update _emit_trace command strings when migrating subprocess to Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to reflect the new surface.

- Old: `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]`
- New: `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the actual call path is a Port method.
