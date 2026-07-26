---
id: 0614
topic: patterns
source_issue: 10616
source_phase: plan
created_at: 2026-07-26T11:05:04.471640+00:00
status: active
corroborations: 1
---

# AgentRunner fan-out is prompt shaping, not worktree machinery

HydraFlow's `AgentRunner` spawns exactly one `claude -p` process. The lead agent inside it fans out via the already-allowlisted `Task` tool — there is no multi-worktree spawn or merge-back infra. To add parallelism, shape the prompt in `src/agent.py` (`_build_tdd_subagent_plan`, ~lines 507/636); do not introduce worktree management.

- Solo: serial prose, no fan-out header.
- Orchestrated: wave-grouped phases, `Task` dispatch per wave, stitch/verify step.

**Why:** Sub-agent orchestration is a prompt-level concern; adding worktree machinery would diverge from HydraFlow's single-worktree model and require ADR changes.
