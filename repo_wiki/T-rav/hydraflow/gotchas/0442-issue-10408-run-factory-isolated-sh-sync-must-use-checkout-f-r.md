---
id: 0442
topic: gotchas
source_issue: 10408
source_phase: plan
created_at: 2026-07-24T05:56:46.873202+00:00
status: superseded
corroborations: 1
superseded_by: 0446
---

# run-factory-isolated.sh sync must use checkout -f, reset --hard, clean -fd in order

The launcher's sync block in `scripts/run-factory-isolated.sh` must run `git checkout -f "$BRANCH"` → `git reset --hard "origin/$BRANCH"` → `git clean -fd` as contiguous commands. A plain `git checkout` aborts under `set -euo pipefail` when a tracked file is dirty, so the following `reset --hard` never executes and the factory silently strands on a stale boot (observed 51+ commits behind).

**Why:** without `-f`, a dirty tracked file makes the whole sync block a no-op instead of a hard reset, and the failure is silent because later commands just never run.
