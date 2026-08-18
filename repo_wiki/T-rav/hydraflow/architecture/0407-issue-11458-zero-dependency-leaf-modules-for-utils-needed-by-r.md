---
id: 0407
topic: architecture
source_issue: 11458
source_phase: plan
created_at: 2026-08-18T12:25:44.377175+00:00
status: active
corroborations: 1
---

# Zero-dependency leaf modules for utils needed by regression_rot_scan

Use zero-dependency leaf modules (no intra-`src/` imports) for shared utilities that `src/regression_rot_scan.py` must consume. `regression_rot_scan.py` deliberately imports nothing from `src/` — importing `src/phase_utils.py` drags a ~24-module closure (`config`, `state`, `ports`, `events`) into a pure scan engine. Pattern: define in a leaf like `src/issue_state.py`, re-export from `src/phase_utils.py` with `# noqa: F401`.

**Why:** Importing `phase_utils` into the scan engine couples a pure analysis tool to the full runtime dependency graph, breaking its isolation guarantee.
