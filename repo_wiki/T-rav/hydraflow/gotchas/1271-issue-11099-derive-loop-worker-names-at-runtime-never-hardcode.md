---
id: 1271
topic: gotchas
source_issue: 11099
source_phase: plan
created_at: 2026-08-14T07:08:09.480579+00:00
status: active
corroborations: 1
---

# Derive loop/worker names at runtime — never hardcode

Do not maintain a hardcoded list of loop names (e.g. `["rc_budget", "repo_wiki", ...]`). Derive names at runtime from the registry or `state.json` worker keys.

A stale hardcoded list silently reports `registered: false` for loops that are actually registered, producing misleading diagnostics that send operators down the wrong path.
**Why:** Hardcoded loop-name lists drift from the registry as new loops are added or renamed, and the failure mode is a false negative with no error signal.
