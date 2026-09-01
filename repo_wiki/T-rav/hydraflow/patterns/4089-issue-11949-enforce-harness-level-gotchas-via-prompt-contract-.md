---
id: 4089
topic: patterns
source_issue: 11949
source_phase: plan
created_at: 2026-09-01T09:56:43.594643+00:00
status: active
corroborations: 1
---

# Enforce harness-level gotchas via prompt contract, not code

When a defect's root cause is harness-level — e.g. the scratchpad path embedding the orchestrator's session id — do not patch the code path. Enforce via prompt-contract + convention + test pins on the surfaces agents actually read: `src/hydraflow_resources/prompts/auto_agent/_envelope.md`, `CLAUDE.md` (in every subagent's system context), and `docs/wiki/gotchas.md`. **Why:** harness patches are fragile and miss the prompt surface; pinning rendered text catches drift at test time.
