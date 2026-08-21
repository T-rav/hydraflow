---
id: 2770
topic: testing
source_issue: 11518
source_phase: plan
created_at: 2026-08-21T09:08:16.052847+00:00
status: active
corroborations: 1
---

# CodeQL cache-poisoning: checkout literal default branch, assert SHA in-job

Fix `actions/cache-poisoning/poisonable-step` alerts by replacing the expression checkout with the literal default branch plus an in-job SHA assertion — not by dismissal.

- `staging-rc-dryrun.yml` `dryrun-shard` uses `with.ref: staging` (the protected default branch, ADR-0042) and a `pin` step asserting `git rev-parse HEAD == needs.resolve.outputs.sha`.
- On mismatch, skip gracefully: `::notice::` + `exit 0`; the workflow's next scheduled tick re-runs the shard.
- Leave the `report` job's job-output-ref checkout alone: with no pip/docker/cache steps it is not poisonable, and it must stay pinned to the tested commit.

**Why:** CodeQL treats `${{ needs.*.outputs.* }}` refs as poisonable when followed by cache-capable steps; a literal protected ref plus a rev-parse assertion preserves the one-SHA-per-report property without the poisonable checkout.
