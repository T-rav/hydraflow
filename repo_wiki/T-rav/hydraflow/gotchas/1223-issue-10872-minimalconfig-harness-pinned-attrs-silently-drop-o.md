---
id: 1223
topic: gotchas
source_issue: 10872
source_phase: plan
created_at: 2026-07-31T05:36:11.799853+00:00
status: active
corroborations: 1
---

# MinimalConfig harness-pinned attrs silently drop overrides

Reject `config_overrides` that name harness-pinned attrs in `scripts/audit_prompts.py`; they silently no-op. `_MinimalConfig.__init__` assigns real attributes for `repo`, `repo_root`, `data_root`, `plans_dir`, `memory_dir`, `repo_data_root`, `repo_memory_dir`, so `__getattr__` never fires and the override vanishes. Maintain an explicit reject list rather than a fall-through. **Why:** A silent drop reopens the harness-vs-production divergence documented in ADR-0116 §9 (the 50_000-vs-15_000 bug).
