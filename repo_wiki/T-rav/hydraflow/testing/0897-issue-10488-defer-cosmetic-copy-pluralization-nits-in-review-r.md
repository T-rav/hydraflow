---
id: 0897
topic: testing
source_issue: 10488
source_phase: review
created_at: 2026-07-25T00:38:26.060862+00:00
status: stale
corroborations: 1
stale_reason: source issue #10488 closed
---

# Defer cosmetic copy/pluralization nits in review rather than unilaterally rewriting seeded test strings

In the #10488 review of `StreamView.jsx` badge copy (`"N · N PR"` singular vs `"N issues · N PRs"` plural), the reviewer flagged inconsistent grammar as LOW but did not fix it, because doing so would require rewriting ~6 hardcoded test assertion strings for a copy call better made deliberately by a human than unilaterally in review. Contrast with the missing-`title`-tooltip finding in the same review, which *was* fixed inline since it was a pure consistency gap with no test-string cost.

**Why:** fixing product-copy nits mid-review risks silently changing user-facing text without product sign-off, distinct from safe mechanical consistency fixes.
