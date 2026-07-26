---
id: 0223
topic: architecture
source_issue: 10579
source_phase: plan
created_at: 2026-07-26T01:24:12.531351+00:00
status: active
corroborations: 1
---

# src/ui: centralize repeated inline-style helpers in src/ui/src/styles/

`subtleBorder(color)` was duplicated verbatim in `StreamCard.jsx:380` and `sectionStyles.js:30`. When fixing bugs in one, add a shared module (`src/ui/src/styles/borderStyles.js` exporting `subtleBorder`/`sideBorders`) instead of patching both copies independently — otherwise fixes drift and only one copy gets the real fix.

**Why:** duplicated style logic across `src/ui/src/components/*` and `src/ui/src/styles/*` is a recurring source of the same bug landing twice, once fixed and once not.
