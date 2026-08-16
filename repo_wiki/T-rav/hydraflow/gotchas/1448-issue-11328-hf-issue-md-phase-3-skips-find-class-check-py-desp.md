---
id: 1448
topic: gotchas
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693271+00:00
status: active
corroborations: 1
---

# hf.issue.md Phase 3 skips find_class_check.py despite CLAUDE.md claim

When a slash-command doc claims a script is wired in, verify the actual command steps. `.claude/commands/hf.issue.md` Phase 3 (lines 66-73) runs a bare `gh issue list --search` and never calls `scripts/find_class_check.py`, but `CLAUDE.md` asserts it does.

- If deferring wiring, file a follow-up issue (the plan's Risk 3 anticipates this).
- Otherwise wire Phase 3 to the script per the plan.

**Why:** Stale CLAUDE.md claims cause future agents to assume class-folding is active when it is library-only, producing silent no-ops.
