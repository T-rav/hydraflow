---
id: 1421
topic: gotchas
source_issue: 11295
source_phase: plan
created_at: 2026-08-16T02:40:08.127288+00:00
status: active
corroborations: 1
---

# Amend existing tests as mutation counter-pins alongside new regression files

When fixing a selection defect in `vitals.js`, amend the existing assertion at `vitals.test.js:111-116` to supply ≥2 active sessions so the test fails if the fix is reverted. New `*.regression.test.js` files alone don't prove the original test would have caught the bug.

The amended test acts as a counter-pin: reverting the fix must make it go red, proving the original blind assertion is closed.

**Why:** Without amending the original assertion, the same defect class could re-enter through the unmodified test path undetected.
