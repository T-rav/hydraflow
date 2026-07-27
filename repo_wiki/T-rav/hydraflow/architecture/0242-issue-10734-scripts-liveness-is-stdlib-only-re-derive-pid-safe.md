---
id: 0242
topic: architecture
source_issue: 10734
source_phase: plan
created_at: 2026-07-27T19:38:38.658607+00:00
status: active
corroborations: 1
---

# scripts/liveness/ is stdlib-only; re-derive PID safety locally

Rule: Modules under `scripts/liveness/` must import only stdlib — never `src/`. The `os.killpg`-only-in-`src/process_group.py` architecture gate does not apply to `scripts/`, so the positive-int / not-self / not-init predicate from `src/process_group.py:is_real_pid` must be re-derived locally before any `killpg`.

- Enforced by `tests/architecture/test_liveness_kernel_no_src_imports.py` (AST scan).

**Why:** Importing `src/` couples boot-time infra to the application package; a wrong PID kill could terminate an unrelated process holding the dashboard port.
