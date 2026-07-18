---
id: 0138
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.606095+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Validate parsers against realistic multi-paragraph agent output

Write parser tests against realistic multi-paragraph transcripts — prose interspersed with structured markers — not bare marker strings.

Example: test input should resemble real `claude` CLI output; assert on structured markers, not prose wording.

**Why:** Bare-marker tests pass even when the parser fails on the surrounding prose context present in real output, hiding real format regressions.
