---
id: 1926
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.565502+00:00
status: superseded
corroborations: 1
supersedes: 1822
superseded_by: 2053
---

# Baseline immutability: only resolved moves, never baseline_snapshot

Only move ADRs into `resolved` in `adr_enforcement_baseline.json`; never edit `baseline_snapshot`. Files under `docs/arch/generated/*` are generator output only.

Example: `make arch-regen` must leave no diff in `docs/arch/generated/adr-enforcement.md`. `test_arch_freshness.py` validates generated docs match generator output.

**Why:** Editing snapshots or hand-editing generated docs desynchronizes baselines from actual violations and breaks freshness tests.
