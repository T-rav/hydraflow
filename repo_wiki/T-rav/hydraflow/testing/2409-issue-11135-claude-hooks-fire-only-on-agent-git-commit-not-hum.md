---
id: 2409
topic: testing
source_issue: 11135
source_phase: plan
created_at: 2026-08-14T13:08:51.035517+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Claude hooks fire only on agent git commit, not human commits

Validation that lives in `.claude/hooks/hf.*.sh` has strictly weaker coverage than the same check in `.githooks/pre-commit`: Claude hooks fire only when an agent shells `git commit`, never on a human terminal commit.

- Move commit-time validation into `.githooks/pre-commit` (covers both paths).
- Reserve `.claude/hooks/` for agent-specific behavior, not shared gates.

**Why:** A gate that only blocks agent commits leaves a hole for human commits and vice versa.
