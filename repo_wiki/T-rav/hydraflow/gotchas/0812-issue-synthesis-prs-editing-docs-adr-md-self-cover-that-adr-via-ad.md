---
id: 0812
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:38:39.536394+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# PRs editing docs/adr/*.md self-cover that ADR via _adr_file_in_diff

When a PR's diff includes `docs/adr/00NN-*.md` itself, `_adr_file_in_diff` treats ADR NN as self-covered for that diff, so a citation/content fix to an ADR won't spuriously drift itself in the same PR.

Example: relevant when writing regression tests for ADR-drift fixes (e.g. issue #10443's fix to ADR-0055:107) — the test only needs to check a *separate* file-only diff (touching `src/base_background_loop.py` alone) to reproduce the drift, not the combined ADR+code diff.

**Why:** Avoids writing a self-contradicting regression test that expects drift on a diff the auditor already exempts.
