---
id: 3323
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:49.185700+00:00
status: active
corroborations: 1
supersedes: 3190
---

# CLI scripts mirror calibrate_finders.py I/O-shell convention

Agent-facing CLI scripts in `scripts/` (e.g. `scripts/find_class_check.py`, `scripts/calibrate_finders.py`) must be thin `gh`-shell wrappers — no business logic, no direct Port calls. Expose `--check` and `--emit-marker` flags that print machine-readable output.

**Why:** Keeps the decision mechanical (agent runs the CLI, reads stdout) rather than agent-judged keyword search. Also enables test-side `gh` shimming per the masked-defect convention without touching Port internals.
