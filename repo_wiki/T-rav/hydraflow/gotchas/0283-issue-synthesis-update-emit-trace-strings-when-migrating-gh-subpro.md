---
id: 0283
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:10:53.480068+00:00
status: superseded
corroborations: 1
supersedes: 0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281
superseded_by: 0288
---

# Update _emit_trace strings when migrating gh subprocess to a Port

Rule: After replacing a `gh`/subprocess call with a Port method, update any `_emit_trace` or telemetry command strings to match the new call surface.

Example: old `command=["gh", "issue", "list", "--label", "wiki-rot-stuck"]` becomes `PRPort.list_closed_issues_by_label("wiki-rot-stuck", limit=50)`.

**Why:** Observability consumers rely on command strings to diagnose failures; stale strings misdirect operators toward subprocess debugging when the real call path is a Port method.
