---
id: 1888
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:26.712150+00:00
status: superseded
corroborations: 1
supersedes: 1790
superseded_by: 1996
---

# Liveness kernel resolves git/events from --workspace, not dev checkout

Pass `--workspace` and resolve `events.jsonl`, `git rev-parse --abbrev-ref HEAD`, and `git fetch --prune` relative to the workspace directory (`~/.hydraflow/factory-workspace/hydraflow`), not the dev checkout where `scripts/factory_liveness_watchdog.py` is installed.

Example: Without `--workspace`, the kernel reads the dev checkout's stale `events.jsonl` and makes false staleness decisions.

**Why:** The installed script location and the factory runtime location are different directories; conflating them produces phantom boot mismatches.
