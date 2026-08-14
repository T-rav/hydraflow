---
id: 1274
topic: gotchas
source_issue: 11106
source_phase: plan
created_at: 2026-08-14T07:39:28.346585+00:00
status: active
corroborations: 1
---

# Filesystem-only inspection avoids new Port surface

Read-only diagnostic tools should read state files, trace JSON, event-log JSONL, and dedup JSON directly — no `gh`, `git`, or `subprocess.run`.

- Works with the orchestrator stopped
- No new Port registration required (ADR-0049 kill-switch N/A)
- Inspector (`src/trust_fleet_inspect.py`) re-runs real `detect_staleness` rather than re-deriving thresholds

**Why:** Subprocess-spawning inspectors couple to live process state, require Port surface, and fail when the orchestrator is down — exactly when you need diagnostics most.
