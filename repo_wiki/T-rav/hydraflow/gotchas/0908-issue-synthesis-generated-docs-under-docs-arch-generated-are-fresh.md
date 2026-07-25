---
id: 0908
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.762020+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# Generated docs under docs/arch/generated/ are freshness-gated, not just regenerated

Changes to generators like `src/arch/generators/adr_cross_reference.py` require running `make arch-regen` and committing the resulting diff to `docs/arch/generated/adr_xref.md` — CI checks that regeneration produces no further diff ("freshness passes"), so an uncommitted or stale generated file fails the build even though the underlying logic is correct.

**Why:** these files are two-writer artifacts (hand-edited generator + machine-regenerated output); skipping the regen step leaves the committed doc out of sync with the generator that CI re-runs.
