---
id: 2380
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T05:19:55.778299+00:00
status: superseded
corroborations: 1
supersedes: 2260
superseded_by: 2500
---

# Treat undeterminable scopes as empty — never exclude

When a maintenance prefix has no determinable write scope in `MAINTENANCE_WRITE_SCOPES`, assign empty scope and never path-exclude in `src/audit/sampling.py`.

Example: `chore(rc):` promotion PRs carry arbitrary staging paths → undeterminable → empty → always sampled. See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** Excluding on incomplete path information would re-open the bypass that path corroboration exists to close.
