---
id: 1145
topic: gotchas
source_issue: 10646
source_phase: plan
created_at: 2026-07-26T12:21:36.986347+00:00
status: active
corroborations: 1
---

# Widening required escape-resolve flags to optional needs at-least-one-of guard

When making `--encoded-as` optional in `scripts/resolve_escape.py` and `resolve_escape()`, add validation that at least one of `encoded_as` or `confidence` is supplied. Without this guard, a flagless `resolve <id>` appends a no-op duplicate row that closes nothing and corrupts the collapse view. Reject with exit 2 and an error naming both flags.

**Why:** An optional-everything command silently succeeds while doing nothing, which is worse than failing loudly.
