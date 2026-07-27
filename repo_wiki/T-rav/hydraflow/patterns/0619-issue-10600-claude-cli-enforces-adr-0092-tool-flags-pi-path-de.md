---
id: 0619
topic: patterns
source_issue: 10600
source_phase: plan
created_at: 2026-07-26T12:25:53.446790+00:00
status: active
corroborations: 1
---

# claude CLI enforces ADR-0092 tool flags; pi path degrades to prose

Prefer the claude CLI path over `_build_pi_command` when ADR-0092 tool restrictions must hold. `src/agent_cli.py:129` shows the claude path enforces `--allowedTools`/`--disallowedTools` natively; `_build_pi_command` degrades these to prompt prose that prompt injection can bypass. **Why:** Prevents privilege escalation through tool-restriction bypass when routing to a fallback provider.
