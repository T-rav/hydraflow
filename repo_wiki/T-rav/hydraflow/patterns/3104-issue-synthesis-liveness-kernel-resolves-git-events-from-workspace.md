---
id: 3104
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:05.546095+00:00
status: active
corroborations: 1
supersedes: 2970
---

# Liveness kernel resolves git/events from --workspace, not dev checkout

Pass `--workspace` and resolve `events.jsonl`, `git rev-parse --abbrev-ref HEAD`, and `git fetch --prune` relative to the workspace directory (`~/.hydraflow/factory-workspace/hydraflow`), not the dev checkout where `scripts/factory_liveness_watchdog.py` is installed.

Example: Without `--workspace`, the kernel reads the dev checkout's stale `events.jsonl` and makes false staleness decisions.

**Why:** The installed script location and the factory runtime location are different directories; conflating them produces phantom boot mismatches.
