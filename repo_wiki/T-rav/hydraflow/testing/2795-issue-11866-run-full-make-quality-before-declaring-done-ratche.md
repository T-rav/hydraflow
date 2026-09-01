---
id: 2795
topic: testing
source_issue: 11866
source_phase: plan
created_at: 2026-09-01T03:52:25.540808+00:00
status: active
corroborations: 1
---

# Run full make quality before declaring done — ratchets need full-suite bake

Several ratchets only fire under full `make quality`, not targeted test subsets: `loop_fitness` coverage, `FakeBackgroundLoop` stub presence, and architecture staleness (`make arch-regen` byte-identical check).
- Lesson from `GateHealthLoop` (#9974): targeted subsets missed all three failure modes.
- Always run the P5 (generated artifacts, glossary, full quality) phase before declaring a loop done.
**Why:** Targeted subsets pass while the full suite fails; a green subset is not a green loop.
