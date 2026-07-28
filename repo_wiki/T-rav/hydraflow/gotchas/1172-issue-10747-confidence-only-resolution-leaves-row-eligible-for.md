---
id: 1172
topic: gotchas
source_issue: 10747
source_phase: plan
created_at: 2026-07-27T22:30:25.835020+00:00
status: stale
corroborations: 1
stale_reason: source issue #10747 closed
---

# Confidence-only resolution leaves row eligible for aging re-surface

When `append_resolution` is called with `attribution_confidence` but no `encoded_as`, the row's `encoded_as` stays `"none-yet"` and the row remains in `list_unresolved`. This is correct: a later aging surfacing can fire under its own fingerprint. The remediation body must state this or operators read the second issue as a bug.

**Why:** Fabricating an encoding to satisfy the old required flag would silently pre-answer the aging surface too.
