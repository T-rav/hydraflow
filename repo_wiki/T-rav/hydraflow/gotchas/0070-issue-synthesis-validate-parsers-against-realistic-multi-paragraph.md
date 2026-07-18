---
id: 0070
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.339921+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Validate parsers against realistic multi-paragraph agent output

Write parser tests against realistic multi-paragraph transcripts — prose interspersed with structured markers — not bare marker strings.

Example: test input should resemble real `claude` CLI output; assert on structured markers, not prose wording, so transcript rewords don't break tests.

**Why:** Bare-marker tests pass even when the parser fails on the surrounding prose context present in real output, hiding real format regressions.
