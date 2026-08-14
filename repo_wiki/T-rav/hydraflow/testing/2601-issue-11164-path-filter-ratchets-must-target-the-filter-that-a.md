---
id: 2601
topic: testing
source_issue: 11164
source_phase: plan
created_at: 2026-08-14T18:58:35.986525+00:00
status: stale
corroborations: 1
stale_reason: source issue #11164 closed
---

# Path-filter ratchets must target the filter that actually gates jobs

When writing a completeness ratchet for `dorny/paths-filter` outputs in `.github/workflows/ci.yml`, assert against the filter that gates the job you care about, not a sibling filter with a similar name. `tests/test_ci_path_filter_completeness.py` ratcheted `python` believing it gated pytest, but `test` jobs are gated on `core_python` — so `agents/**` (in `python`, absent from `core_python`) slipped through.

**Why:** A ratchet watching the wrong filter gives false confidence that a gate is reachable when it is not.
