---
id: 0182
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.151207+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Update _emit_trace command strings when migrating subprocess to Port

After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to reflect the new surface.

Example: Old: `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]`. New: `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the actual call path is a Port method.
