---
id: 1233
topic: gotchas
source_issue: 10885
source_phase: plan
created_at: 2026-07-31T07:40:02.824274+00:00
status: active
corroborations: 1
---

# Table ⇄ function sync test prevents credential key drift

Maintain a bidirectional sync test in `tests/test_credentials.py` between `CREDENTIAL_ENV_KEYS` and the keys `build_credentials` actually reads.

- Declaring a key in the table that the function never reads fails (no dead entries).
- Reading an env key not declared in the table fails (no hidden leakage surface).
- Every `Credentials` model field must appear as a mapping key.

**Why:** Without bidirectional enforcement, the declaration table and the resolution chain silently diverge — the table becomes untrustworthy as the isolation source of truth.
