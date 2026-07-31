---
id: 1463
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T16:53:02.237842+00:00
status: superseded
corroborations: 1
supersedes: 1384
superseded_by: 1547
---

# Treat undeterminable scopes as empty — never exclude

When a maintenance prefix has no determinable write scope in `MAINTENANCE_WRITE_SCOPES`, assign empty scope and never path-exclude in `src/audit/sampling.py`.

Example: `chore(rc):` promotion PRs carry arbitrary staging paths → undeterminable → empty → always sampled. Empty-path-set merges are also no longer excluded (deliberate).

**Why:** Excluding on incomplete path information would re-open the bypass that path corroboration exists to close.
