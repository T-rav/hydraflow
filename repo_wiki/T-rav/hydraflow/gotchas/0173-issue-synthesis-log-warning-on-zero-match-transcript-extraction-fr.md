---
id: 0173
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.955638+00:00
status: superseded
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
superseded_by: 0180
---

# Log warning on zero-match transcript extraction from non-empty input

When extracting structured data from CLI transcripts, wrap regex in try/except and log a warning on zero matches against non-empty input.

Example: `matches = RE.findall(text); if not matches and text.strip(): logger.warning('parser found 0 matches on non-empty transcript')`.

**Why:** Silent zero-match returns hide format drift between transcript versions; warnings surface parser breakage before it causes downstream data loss.
