---
id: 0668
topic: patterns
source_issue: 10734
source_phase: plan
created_at: 2026-07-27T19:38:38.658587+00:00
status: superseded
corroborations: 1
superseded_by: 0713
---

# Liveness kernel resolves git/events from --workspace, not dev checkout

Rule: The installed `scripts/factory_liveness_watchdog.py` runs from the dev checkout, but factory events and git state live in `~/.hydraflow/factory-workspace/hydraflow`. Always pass `--workspace` and resolve `events.jsonl`, `rev-parse --abbrev-ref HEAD`, and `git fetch --prune` relative to it.

- Without `--workspace`, the kernel reads the dev checkout's stale `events.jsonl` and makes false staleness decisions.

**Why:** The installed script location and the factory runtime location are different directories; conflating them produces phantom boot mismatches.
