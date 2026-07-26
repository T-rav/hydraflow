---
id: 1027
topic: gotchas
source_issue: 10564
source_phase: plan
created_at: 2026-07-25T23:31:13.809603+00:00
status: active
corroborations: 1
---

# Border-conflict matcher needs an explicit sub-property allowlist, not a `border` prefix check

In `src/ui/src/test/styleConflicts.js`'s `findBorderShorthandConflicts`, a naive `key.startsWith('border')` check flags `borderRadius`, `borderCollapse`, `borderSpacing`, and `borderImage*` as conflicts even though they aren't `border` sub-properties — these co-occur with `border` shorthand in `sessionBox`, `reportBtn`, and `trackerBtn`, so a naive matcher fails the whole Header suite. Enumerate only true border-box sub-properties (`borderWidth/Style/Color` and the `Top/Right/Bottom/Left` variants).

**Why:** an over-broad matcher produces false positives across unrelated, correctly-written styles, not just the one bug being fixed.
