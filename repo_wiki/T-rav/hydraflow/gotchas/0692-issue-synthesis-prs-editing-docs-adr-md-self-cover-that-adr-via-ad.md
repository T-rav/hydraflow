---
id: 0692
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.491160+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# PRs editing docs/adr/*.md self-cover that ADR via _adr_file_in_diff

When a PR's diff includes `docs/adr/00NN-*.md` itself, `_adr_file_in_diff` treats ADR NN as self-covered for that diff, so a citation/content fix to an ADR won't spuriously drift itself in the same PR.

Example: relevant when writing regression tests for ADR-drift fixes (e.g. issue #10443's fix to ADR-0055:107) — the test only needs to check a *separate* file-only diff (touching `src/base_background_loop.py` alone) to reproduce the drift, not the combined ADR+code diff.

**Why:** Avoids writing a self-contradicting regression test that expects drift on a diff the auditor already exempts.
