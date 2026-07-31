---
id: 1230
topic: gotchas
source_issue: 10878
source_phase: plan
created_at: 2026-07-31T07:10:49.839600+00:00
status: active
corroborations: 1
---

# ADDING-A-GATE.md ordering rule: job must be green before requiring

Before adding a gate to `required_on` in `gates.toml`, verify the underlying job is already green on the target branch. This is step 4 of `ADDING-A-GATE.md`.

Example: `CI Gate` (job `ci-gate` in `ci.yml`) was already required and green on `staging` live, so declaring it in the contract could not self-block its own introducing PR.

**Why:** A newly-required-but-red gate fails the PR's own branch protection check, deadlocking the change — the introducing PR can never merge to make itself pass.
