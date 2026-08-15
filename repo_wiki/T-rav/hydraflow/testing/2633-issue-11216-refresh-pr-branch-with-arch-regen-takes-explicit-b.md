---
id: 2633
topic: testing
source_issue: 11216
source_phase: plan
created_at: 2026-08-15T05:44:56.799510+00:00
status: active
corroborations: 1
---

# refresh_pr_branch_with_arch_regen takes explicit base for non-staging targets

`PRPort.refresh_pr_branch_with_arch_regen` (`src/ports.py:227`) hardcodes `config.base_branch()` (staging). Add a keyword-only `base: str | None = None`; `None` defaults to `config.base_branch()`, preserving `DependabotMergeLoop` behavior. Pass `base=main_branch` to heal RC conflicts.

- `PRManager` (`src/pr_manager.py:2823`) mirrors the signature; `tests/test_ports.py` asserts parity.

**Why:** Without a base override, the heal path merges staging into the RC head instead of main, which does not resolve the conflict.
