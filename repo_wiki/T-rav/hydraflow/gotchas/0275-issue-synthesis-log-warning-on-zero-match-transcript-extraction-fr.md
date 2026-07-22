---
id: 0275
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.032418+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Log warning on zero-match transcript extraction from non-empty input

When extracting structured data from CLI transcripts, wrap regex in try/except and log a warning on zero matches against non-empty input.

Example: `matches = RE.findall(text); if not matches and text.strip(): logger.warning('parser found 0 matches on non-empty transcript')`.

**Why:** Silent zero-match returns hide format drift between transcript versions; warnings surface parser breakage before it causes downstream data loss.

See also: gotchas — Validate parsers against realistic multi-paragraph agent output.
