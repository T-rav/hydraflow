---
id: 0274
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.031990+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Validate parsers against realistic multi-paragraph agent output

Write parser tests against realistic multi-paragraph transcripts — prose interspersed with structured markers — not bare marker strings.

Example: test input should resemble real `claude` CLI output; assert on structured markers, not prose wording.

**Why:** Bare-marker tests pass even when the parser fails on the surrounding prose context present in real output, hiding real format regressions.

See also: gotchas — Log warning on zero-match transcript extraction from non-empty input.
