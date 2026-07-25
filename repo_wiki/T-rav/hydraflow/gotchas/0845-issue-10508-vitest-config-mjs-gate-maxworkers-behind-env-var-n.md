---
id: 0845
topic: gotchas
source_issue: 10508
source_phase: plan
created_at: 2026-07-25T04:34:17.689744+00:00
status: active
corroborations: 1
---

# vitest.config.mjs: gate maxWorkers behind env var, never hardcode testTimeout

Bound vitest's worker pool with `maxWorkers: process.env.VITEST_MAX_WORKERS || undefined` in `src/ui/vitest.config.mjs`, and do not add a global `test.testTimeout` override as a workaround for oversubscription.

- Unset `VITEST_MAX_WORKERS` → vitest's default pool width (used by `make test-ui`, CI)
- Set (e.g. `VITEST_MAX_WORKERS=2` from `make quality`) → pool capped, default 5000ms `testTimeout` stays meaningful

**Why:** inflating `testTimeout` masks CPU starvation instead of fixing it — a hung test (e.g. `SystemPanel.test.jsx`) should still fail at 5000ms rather than being hidden by a longer global timeout.
