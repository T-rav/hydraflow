---
id: 1281
topic: gotchas
source_issue: 11095
source_phase: plan
created_at: 2026-08-14T08:32:23.164111+00:00
status: active
corroborations: 1
---

# SubagentStop hooks must fail open, single-block, and carry a kill-switch

Subagent stop hooks in hydraflow follow three rules: (1) fail open (exit 0) on missing/unparseable transcripts; (2) honor `stop_hook_active` to block at most once per stop chain, preventing infinite loops; (3) honor an env-var kill-switch following the `.githooks/pre-push` precedent.

Example: `HYDRAFLOW_DISABLE_SUBAGENT_STALL_GUARD=1` bypasses the guard entirely.

**Why:** A stop hook that false-positives traps subagents in a loop; a hook that fails closed blocks legitimate work when payload shape assumptions are wrong.
