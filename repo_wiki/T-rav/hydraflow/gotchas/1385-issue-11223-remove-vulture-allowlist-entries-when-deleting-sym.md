---
id: 1385
topic: gotchas
source_issue: 11223
source_phase: plan
created_at: 2026-08-15T06:46:05.624556+00:00
status: active
corroborations: 1
---

# Remove vulture allowlist entries when deleting symbols

When deleting dead code that vulture previously allowlisted (e.g. `_check_sha_skip_guard` in `src/review_phase/_phase.py`), also remove the matching entry from the vulture whitelist. Otherwise `make quality` reports a stale-whitelist finding even though the underlying symbol no longer exists.

**Why:** Stale whitelist entries fail the quality gate independently of the code change itself.
