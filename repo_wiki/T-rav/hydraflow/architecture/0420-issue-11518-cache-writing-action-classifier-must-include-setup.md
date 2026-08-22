---
id: 0420
topic: architecture
source_issue: 11518
source_phase: review
created_at: 2026-08-21T12:23:02.881190+00:00
status: active
corroborations: 1
---

# Cache-writing action classifier must include setup-* default-caching actions

When auditing GitHub Actions for cache-enabling patterns, check both explicit cache-enabling inputs AND setup-* actions that enable caching by default.

Example: `.github/workflows/quality.yml:168` has setup-go without explicit cache input but still caches; `_is_cache_writing()` in `tests/architecture/test_staging_rc_dryrun_workflow_shape.py:88-97` only checks explicit inputs, missing this case.

**Why:** Default-caching setup-* actions silently bypass fleet sweeps designed to prevent cache-poisoning shapes, re-enabling security alerts without detection.
