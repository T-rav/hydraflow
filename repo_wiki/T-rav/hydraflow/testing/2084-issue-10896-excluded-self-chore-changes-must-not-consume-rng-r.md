---
id: 2084
topic: testing
source_issue: 10896
source_phase: plan
created_at: 2026-07-31T12:32:01.782699+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Excluded self-chore changes must not consume rng randomness

In `select_sample`, an excluded self-chore change skips the `rng.random()` draw entirely. The gauntlet bypass must not introduce an unconditional draw for excluded paths.

- `test_excluded_change_does_not_perturb_seeded_selection` asserts a 30-change batch's selection is byte-identical with or without an excluded change

**Why:** Seed determinism for surrounding real changes must be unperturbed — any spurious rng consumption shifts downstream picks and breaks reproducible audits.
