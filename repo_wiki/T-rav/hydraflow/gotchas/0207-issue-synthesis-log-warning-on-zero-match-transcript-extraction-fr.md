---
id: 0207
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.159728+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Log warning on zero-match transcript extraction from non-empty input

When extracting structured data from CLI transcripts, wrap regex in try/except and log a warning on zero matches against non-empty input.

Example: `matches = RE.findall(text); if not matches and text.strip(): logger.warning('parser found 0 matches on non-empty transcript')`.

**Why:** Silent zero-match returns hide format drift between transcript versions; warnings surface parser breakage before it causes downstream data loss.
