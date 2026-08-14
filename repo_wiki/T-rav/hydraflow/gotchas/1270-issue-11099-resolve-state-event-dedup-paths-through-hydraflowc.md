---
id: 1270
topic: gotchas
source_issue: 11099
source_phase: plan
created_at: 2026-08-14T07:08:09.480559+00:00
status: active
corroborations: 1
---

# Resolve state/event/dedup paths through HydraFlowConfig

Repo-scoped path resolution (`_resolve_repo_scoped_paths`) means `state_file` and `event_log_path` live under `<data_root>/<repo>/`, not at the top level. Hand-building paths like `data_root / "state.json"` silently points to the wrong location. Always resolve through `HydraFlowConfig` to get correct repo-scoped paths.

Additionally, a rotated `events.jsonl` may have dropped the window you need — report each source's presence and age in diagnostic output so the operator knows what's missing.
**Why:** Wrong path resolution produces empty diagnostics with no error, making stale-loop debugging impossible and masking the real cause.
