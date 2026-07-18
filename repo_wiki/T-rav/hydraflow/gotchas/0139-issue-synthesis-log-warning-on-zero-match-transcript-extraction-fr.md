---
id: 0139
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.606538+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Log warning on zero-match transcript extraction from non-empty input

When extracting structured data from CLI transcripts, wrap regex in try/except and log a warning on zero matches against non-empty input.

Example: `matches = RE.findall(text); if not matches and text.strip(): logger.warning('parser found 0 matches on non-empty transcript')`.

**Why:** Silent zero-match returns hide format drift between transcript versions; warnings surface parser breakage before it causes downstream data loss.
