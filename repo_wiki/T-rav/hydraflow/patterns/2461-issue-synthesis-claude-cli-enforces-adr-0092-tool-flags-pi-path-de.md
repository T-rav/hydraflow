---
id: 2461
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:23.352337+00:00
status: superseded
corroborations: 1
supersedes: 2341
superseded_by: 2584
---

# claude CLI enforces ADR-0092 tool flags; pi path degrades to prose

Prefer the claude CLI path over `_build_pi_command` when ADR-0092 tool restrictions must hold. The claude path enforces `--allowedTools`/`--disallowedTools` natively; `_build_pi_command` degrades these to prompt prose that prompt injection can bypass.

Example: Route through `agent_cli.build_agent_command` (`src/agent_cli.py:129`) when tool restrictions are security-critical.

**Why:** Prevents privilege escalation through tool-restriction bypass when routing to a fallback provider.
