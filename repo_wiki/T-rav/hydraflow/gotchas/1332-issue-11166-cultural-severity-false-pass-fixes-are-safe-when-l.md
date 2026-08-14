---
id: 1332
topic: gotchas
source_issue: 11166
source_phase: plan
created_at: 2026-08-14T19:18:14.572511+00:00
status: active
corroborations: 1
---

# CULTURAL-severity false-PASS fixes are safe when live CLAUDE.md carries the rule

Tightening a CULTURAL-severity check from false PASS to true FAIL cannot break this repo's own audit, provided the live `CLAUDE.md` satisfies the rule literally.

Before merging any p8 anchor fix, run `make audit` (not a file-targeted subset) to confirm P8.7 still reports PASS for the repo itself.

**Why:** A CULTURAL gate that newly FAILs on the live repo would block the audit pipeline; the `make audit` gate catches this before merge.
