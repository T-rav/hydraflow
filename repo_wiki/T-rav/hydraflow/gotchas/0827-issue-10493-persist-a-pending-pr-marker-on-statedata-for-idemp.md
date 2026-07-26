---
id: 0827
topic: gotchas
source_issue: 10493
source_phase: plan
created_at: 2026-07-24T23:45:36.554288+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Persist a pending-PR marker on StateData for idempotent re-pick recovery

When PR creation may have partially succeeded (e.g. `gh pr create` ran but the response was lost to a reap), record a `StateData.pending_prs: dict[issue -> branch]` marker instead of silently retrying the full build. On re-pick, `src/implement_phase.py` checks the marker first and short-circuits: re-query for an already-open PR, adopt it if found, and clear the marker — without re-running the agent. Only clear the marker once a PR is opened or confirmed to exist.

**Why:** without a marker, re-pick reruns the whole build from scratch on work that already landed, wasting attempt budget and risking duplicate branches.
