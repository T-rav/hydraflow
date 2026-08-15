---
id: 2635
topic: testing
source_issue: 11217
source_phase: plan
created_at: 2026-08-15T06:04:15.266872+00:00
status: active
corroborations: 1
---

# Full `make quality` is the only gate for loop wiring completeness

When adding a new caretaker loop (`OrphanBranchLoop`) or PRPort method (`get_branch_head_sha`, `list_recently_merged_prs`), only full `make quality` catches missing wiring checkpoints, cassettes, or kill-switch config.

Individual test tiers (unit, scenario) pass with incomplete wiring. Run `make arch-regen` first to regenerate `docs/arch/functional_areas.yml`, then `make quality` for loop-wiring, kill-switch, fitness, and ports gates together.

**Why:** A missing cassette or unregistered loop silently passes unit tests but fails the integration gates that `make quality` aggregates.
