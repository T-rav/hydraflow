---
id: 1419
topic: gotchas
source_issue: 11286
source_phase: plan
created_at: 2026-08-16T01:54:47.585529+00:00
status: active
corroborations: 1
---

# Verify referenced PR/issue numbers exist before building on them

Rule: Before treating a PR or issue as a prerequisite in `T-rav/hydraflow`, confirm it has a real ref (PR number, commit, or branch). Don't trust prose claims like "#11239 slice PR."

Example: Issues #11276/#11277 both credited a "#11239 slice PR" that never existed (no PR, no ref). #11286 triage caught it and landed the seams for real.

**Why:** Building on phantom prerequisites leaves dependencies unmet and blocks downstream issues silently.
