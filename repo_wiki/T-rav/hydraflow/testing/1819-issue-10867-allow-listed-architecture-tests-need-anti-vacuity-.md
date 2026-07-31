---
id: 1819
topic: testing
source_issue: 10867
source_phase: plan
created_at: 2026-07-31T03:20:17.216750+00:00
status: active
corroborations: 1
---

# Allow-listed architecture tests need anti-vacuity and stale-entry checks

A check that passes only because every duplicate is allow-listed is flagged tautological by `check_is_tautological`. Pair every allow-list with:

- Synthetic `tmp_path` fixtures proving the scanner fires on a newly-introduced duplicate.
- A test that fails when an allow-listed pair is no longer duplicated (prevents stale entries).
- Each entry must carry a one-line justification naming both owning modules.

**Why:** Without anti-vacuity proofs, the check is advisory, not asserting.
