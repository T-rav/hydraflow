---
id: 1822
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.275397+00:00
status: superseded
corroborations: 1
supersedes: 1726
superseded_by: 1920
---

# Treat undeterminable scopes as empty — never exclude

When a maintenance prefix has no determinable write scope in `MAINTENANCE_WRITE_SCOPES`, assign empty scope and never path-exclude in `src/audit/sampling.py`.

Example: `chore(rc):` promotion PRs carry arbitrary staging paths → undeterminable → empty → always sampled. Empty-path-set merges are also no longer excluded (deliberate). See also: [patterns] — Self-chore exclusion requires path corroboration.

**Why:** Excluding on incomplete path information would re-open the bypass that path corroboration exists to close.
