---
id: 1822
topic: testing
source_issue: 10868
source_phase: plan
created_at: 2026-07-31T03:28:15.424926+00:00
status: superseded
corroborations: 1
superseded_by: 1926
---

# Baseline immutability: only resolved moves, never baseline_snapshot

Only move ADRs into `resolved` in `adr_enforcement_baseline.json`; never edit `baseline_snapshot`. Files under `docs/arch/generated/*` are generator output only.

- Adding ADR-0025/0035 to `resolved` shrinks the ratchet window.
- `make arch-regen` must leave no diff in `docs/arch/generated/adr-enforcement.md`.
- `test_arch_freshness.py` validates generated docs match generator output.

**Why:** Editing snapshots or hand-editing generated docs desynchronizes baselines from actual violations and breaks freshness tests.
