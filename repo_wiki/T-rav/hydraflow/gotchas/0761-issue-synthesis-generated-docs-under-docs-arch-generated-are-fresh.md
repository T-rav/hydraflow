---
id: 0761
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.931041+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Generated docs under docs/arch/generated/ are freshness-gated, not just regenerated

Changes to generators like `src/arch/generators/adr_cross_reference.py` require running `make arch-regen` and committing the resulting diff to `docs/arch/generated/adr_xref.md` — CI checks that regeneration produces no further diff ("freshness passes"), so an uncommitted or stale generated file fails the build even though the underlying logic is correct.

**Why:** these files are two-writer artifacts (hand-edited generator + machine-regenerated output); skipping the regen step leaves the committed doc out of sync with the generator that CI re-runs.
