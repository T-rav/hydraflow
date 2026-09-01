---
id: 4088
topic: patterns
source_issue: 11949
source_phase: plan
created_at: 2026-09-01T09:56:43.594592+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Sibling subagents share orchestrator scratchpad dir

Every HydraFlow-dispatched agent session — auto-agent dispatches and orchestrator-spawned subagents — writes into the orchestrator's scratchpad dir, because the path embeds the orchestrator's session id. Prefix every file with the task slug (`flaky-42-pr-body.md`), never bare `pr_body.md` / `quality.log` / `notes.md`; use unique terminal markers per task, not bare `EXIT=`. The rule is surfaced via `src/hydraflow_resources/prompts/auto_agent/_envelope.md`. **Why:** bare names collide silently between siblings, corrupting PR bodies and logs.
