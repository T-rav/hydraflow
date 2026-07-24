---
id: 0577
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.218332+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Verify new ADR headers by running make arch-regen before committing

After drafting a new ADR file, run `make arch-regen` and inspect `docs/arch/generated/adr-conformance.md` to confirm the new ADR appears with a non-"missing" Enforcement kind, and that `adr_cross_reference` resolves every Related/Refines link — don't hand-verify header shape by eye.

Example: ADR-0108's plan mitigates "dangling metadata" risk by cloning ADR-0102's header shape (`**Status:**`, `**Enforcement:** enforced`, `**Enforced by:**`) and checking regenerated output before commit.

**Why:** A missing Enforcement kind or a Related/Refines link to a nonexistent file fails `adr-conformance`/xref CI, and `make quality` won't catch it until arch-regen is actually run.
