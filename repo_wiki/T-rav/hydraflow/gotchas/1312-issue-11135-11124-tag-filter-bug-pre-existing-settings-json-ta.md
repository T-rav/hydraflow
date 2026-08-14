---
id: 1312
topic: gotchas
source_issue: 11135
source_phase: plan
created_at: 2026-08-14T13:08:51.035640+00:00
status: active
corroborations: 1
---

# #11124 tag-filter bug: pre-existing settings.json takes broken merge branch

Issue #11124 introduced a tag-filter bug in `scripts/merge_assets.py` where targets with a pre-existing `.claude/settings.json` take a broken merge branch. Regression tests that exercise `merge_assets` must stay on the **fresh-target path** to avoid false failures from this unrelated bug.

- Use a clean `fresh_target` with no prior `.claude/` directory.
- Do not pre-create `settings.json` in test fixtures unless testing #11124 itself.

**Why:** Mixing the two bugs in one test produces ambiguous RED pins — you cannot tell which bug caused the failure.
