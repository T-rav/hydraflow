---
id: 2623
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T08:32:48.930460+00:00
status: superseded
corroborations: 1
supersedes: 2500
superseded_by: 2746
---

# Treat undeterminable scopes as empty — never exclude

When a maintenance prefix has no determinable write scope in `MAINTENANCE_WRITE_SCOPES`, assign empty scope and never path-exclude in `src/audit/sampling.py`.

Example: `chore(rc):` promotion PRs carry arbitrary staging paths → undeterminable → empty → always sampled. See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** Excluding on incomplete path information would re-open the bypass that path corroboration exists to close.
