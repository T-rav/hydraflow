---
id: 1157
topic: testing
source_issue: 10583
source_phase: plan
created_at: 2026-07-26T02:28:58.639379+00:00
status: active
corroborations: 1
---

# Split pure scanner from repo-guard test for style-rule enforcement

When adding a source-scanning guard in `src/ui`, separate the pure detection logic (e.g. `src/ui/src/test/borderShorthandScan.js`) from the test that both pins its semantics on fixtures and performs the actual repo sweep (`__tests__/borderShorthandScan.test.js`). The scanner tracks JSX/object nesting so sibling style objects aren't conflated, and treats unparseable source as a finding rather than a silent skip.

**Why:** fixture-level tests catch scanner regressions directly, while the repo sweep just walks the tree — so new components are covered automatically with no list to maintain.
