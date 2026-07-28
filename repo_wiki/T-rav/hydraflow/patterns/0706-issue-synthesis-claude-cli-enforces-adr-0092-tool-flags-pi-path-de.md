---
id: 0706
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:37:52.937886+00:00
status: superseded
corroborations: 1
supersedes: 0661
superseded_by: 0763
---

# claude CLI enforces ADR-0092 tool flags; pi path degrades to prose

Prefer the claude CLI path over `_build_pi_command` when ADR-0092 tool restrictions must hold. `src/agent_cli.py:129` shows the claude path enforces `--allowedTools`/`--disallowedTools` natively; `_build_pi_command` degrades these to prompt prose that prompt injection can bypass.

Example: Route through `agent_cli.build_agent_command` when tool restrictions are security-critical.

**Why:** Prevents privilege escalation through tool-restriction bypass when routing to a fallback provider.
