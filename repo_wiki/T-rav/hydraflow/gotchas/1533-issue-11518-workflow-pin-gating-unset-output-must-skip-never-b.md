---
id: 1533
topic: gotchas
source_issue: 11518
source_phase: plan
created_at: 2026-08-21T09:08:16.052885+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Workflow pin gating: unset output must skip, never build (fail-safe if:)

Gate downstream workflow steps on the verification step's output so an unset value fails safe.

- `staging-rc-dryrun.yml` `dryrun-shard`: every step after `pin` carries `if: steps.pin.outputs.matched == 'true'`; uploads compose guards — `if: always() && steps.pin.outputs.matched == 'true'` for the summary, `if: failure() && …` for failure artifacts.
- A crashed `pin` step leaves `matched` unset (`''`), so `'' != 'true'` skips setup-python/pip/docker — the shard can never build unasserted code.

**Why:** The dangerous failure mode is running build/cache steps without the SHA assertion; composing the pin check into every later `if:` makes missing output equivalent to refusal, mirroring the rule that CI gate pins must evaluate the `if:` condition itself, not just step existence.
