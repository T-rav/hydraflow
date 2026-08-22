---
id: 2776
topic: testing
source_issue: 11518
source_phase: review
created_at: 2026-08-21T12:23:02.881220+00:00
status: active
corroborations: 1
---

# CodeQL cache-poisoning defense: literal-ref + in-job SHA assertion

In workflow jobs with expression-ref checkouts and output SHA pinning, use a literal ref for the cache-key source (e.g., `ref: staging`) and assert the SHA inside the job before using it in privileged operations. Document the boundary with TRUST comments.

Example: `scripts/staging_rc_dryrun_pin.py` and `.github/workflows/staging-rc-dryrun.yml` checkout `ref: staging` for cache, assert SHA in-job before downstream use.

**Why:** Expression-ref checkout with cache keys derived from the checked-out SHA enables cache-poisoning attacks; literal refs with in-job assertions prevent substitution.
