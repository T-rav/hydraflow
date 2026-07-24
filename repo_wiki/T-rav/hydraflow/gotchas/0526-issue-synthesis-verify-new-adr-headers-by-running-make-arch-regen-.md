---
id: 0526
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.794624+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Verify new ADR headers by running make arch-regen before committing

After drafting a new ADR file, run `make arch-regen` and inspect `docs/arch/generated/adr-conformance.md` to confirm the new ADR appears with a non-"missing" Enforcement kind, and that `adr_cross_reference` resolves every Related/Refines link — don't hand-verify header shape by eye.

Example: ADR-0108's plan mitigates "dangling metadata" risk by cloning ADR-0102's header shape (`**Status:**`, `**Enforcement:** enforced`, `**Enforced by:**`) and checking regenerated output before commit.

**Why:** A missing Enforcement kind or a Related/Refines link to a nonexistent file fails `adr-conformance`/xref CI, and `make quality` won't catch it until arch-regen is actually run.
