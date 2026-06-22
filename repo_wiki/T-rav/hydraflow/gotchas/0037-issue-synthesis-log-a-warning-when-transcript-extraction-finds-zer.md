---
id: 0037
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.697666+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Log a warning when transcript extraction finds zero matches on non-empty input

When extracting structured data from CLI transcripts, wrap regex in try/except and log a warning on zero matches against non-empty input.

Example: `matches = RE.findall(text); if not matches and text.strip(): logger.warning('parser found 0 matches on non-empty transcript')`.

**Why:** Silent zero-match returns hide format drift between transcript versions; warnings surface parser breakage before it causes downstream data loss.
