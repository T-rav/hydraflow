---
id: 0161
topic: architecture
source_issue: 10393
source_phase: plan
created_at: 2026-07-24T04:45:18.082057+00:00
status: active
corroborations: 1
---

# os.killpg is structurally confined to src/process_group.py — fix the one predicate

`tests/architecture/test_process_group_kill_guard.py` enforces that `os.killpg` only appears in `src/process_group.py`. Every reap path — `execution._reap_process_group`, `runner_utils.terminate_processes`, `reap_all_tracked` — funnels through `kill_process_group` → `is_real_pid`. When hardening kill-signal safety, fix the single predicate rather than adding guards at each call site.

**Why:** the architecture guard test makes scattered `os.killpg` guards impossible to land cleanly, so predicate-level fixes are both the correct and the only reachable approach.
