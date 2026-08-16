---
id: 3567
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.885709+00:00
status: active
corroborations: 1
supersedes: 3420
---

# Capture history inside state setters, not in loop call sites

When adding a history ring for a state field, append inside the setter, not in loop call sites.

Example: `set_prompt_efficiency_baseline` in `src/prompt_efficiency.py` captures history; `skill_prompt_eval_loop.py` and any future caller drive the setter directly, so history capture is automatic.

**Why:** Call-site appends get skipped when the setter is invoked from a new path; setter-side capture is path-invariant and keeps trailing-window semantics unchanged.
