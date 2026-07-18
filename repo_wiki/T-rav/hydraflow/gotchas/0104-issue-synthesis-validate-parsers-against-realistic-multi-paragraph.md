---
id: 0104
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:33:11.848268+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Validate parsers against realistic multi-paragraph agent output

Write parser tests against realistic multi-paragraph transcripts — prose interspersed with structured markers — not bare marker strings.

Example: test input should resemble real `claude` CLI output; assert on structured markers, not prose wording, so transcript rewords don't break tests.

**Why:** Bare-marker tests pass even when the parser fails on the surrounding prose context present in real output, hiding real format regressions.
