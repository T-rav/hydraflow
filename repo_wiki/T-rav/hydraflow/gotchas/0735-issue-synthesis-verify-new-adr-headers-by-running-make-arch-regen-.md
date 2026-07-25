---
id: 0735
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.854469+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# Verify new ADR headers by running make arch-regen before committing

After drafting a new ADR file, run `make arch-regen` and inspect `docs/arch/generated/adr-conformance.md` to confirm the new ADR appears with a non-"missing" Enforcement kind, and that `adr_cross_reference` resolves every Related/Refines link — don't hand-verify header shape by eye.

Example: ADR-0108's plan mitigates "dangling metadata" risk by cloning ADR-0102's header shape (`**Status:**`, `**Enforcement:** enforced`, `**Enforced by:**`) and checking regenerated output before commit.

**Why:** A missing Enforcement kind or a Related/Refines link to a nonexistent file fails `adr-conformance`/xref CI, and `make quality` won't catch it until arch-regen is actually run.
