---
id: 1224
topic: gotchas
source_issue: 10872
source_phase: plan
created_at: 2026-07-31T05:36:11.799868+00:00
status: active
corroborations: 1
---

# Pin new AuditTarget names in PROMPT_BASELINE same commit as registry

When adding a new `AuditTarget` to the registry in `scripts/audit_prompts.py`, pin its name in `src/prompt_fitness.py`'s `PROMPT_BASELINE` in the same commit. `test_baseline_covers_every_scored_prompt` fails on any scored target lacking a baseline entry. **Why:** The completeness gate treats a missing baseline as a regression, so an unpinned variant blocks CI and looks indistinguishable from a real prompt-loss bug.
