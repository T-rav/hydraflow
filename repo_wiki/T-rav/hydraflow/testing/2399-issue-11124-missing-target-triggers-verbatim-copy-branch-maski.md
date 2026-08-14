---
id: 2399
topic: testing
source_issue: 11124
source_phase: plan
created_at: 2026-08-14T11:33:53.102484+00:00
status: active
corroborations: 1
---

# Missing target triggers verbatim-copy branch, masking merge bugs

Regression tests for `merge_settings_file` must pre-create the target settings file with real user content. If the target is absent, the function copies the source verbatim, bypassing the tag-filter merge logic entirely.

A test asserting "all 14 hf scripts present" passes against pre-fix (untagged) code when the target doesn't exist — the verbatim copy includes everything regardless of tags.

**Why:** Tests that only exercise the copy branch cannot detect bugs in the merge branch; they pass for the wrong reason.
