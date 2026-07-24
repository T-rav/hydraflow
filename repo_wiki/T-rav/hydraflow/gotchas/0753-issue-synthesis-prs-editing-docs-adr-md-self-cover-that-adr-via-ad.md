---
id: 0753
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.910153+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# PRs editing docs/adr/*.md self-cover that ADR via _adr_file_in_diff

When a PR's diff includes `docs/adr/00NN-*.md` itself, `_adr_file_in_diff` treats ADR NN as self-covered for that diff, so a citation/content fix to an ADR won't spuriously drift itself in the same PR.

Example: relevant when writing regression tests for ADR-drift fixes (e.g. issue #10443's fix to ADR-0055:107) — the test only needs to check a *separate* file-only diff (touching `src/base_background_loop.py` alone) to reproduce the drift, not the combined ADR+code diff.

**Why:** Avoids writing a self-contradicting regression test that expects drift on a diff the auditor already exempts.
