---
id: 0882
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.732882+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# Verify new ADR headers by running make arch-regen before committing

After drafting a new ADR file, run `make arch-regen` and inspect `docs/arch/generated/adr-conformance.md` to confirm the new ADR appears with a non-"missing" Enforcement kind, and that `adr_cross_reference` resolves every Related/Refines link — don't hand-verify header shape by eye.

Example: ADR-0108's plan mitigates "dangling metadata" risk by cloning ADR-0102's header shape (`**Status:**`, `**Enforcement:** enforced`, `**Enforced by:**`) and checking regenerated output before commit.

**Why:** A missing Enforcement kind or a Related/Refines link to a nonexistent file fails `adr-conformance`/xref CI, and `make quality` won't catch it until arch-regen is actually run.
