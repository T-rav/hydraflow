---
id: 3470
topic: patterns
source_issue: 11321
source_phase: plan
created_at: 2026-08-16T09:00:03.766442+00:00
status: superseded
corroborations: 1
superseded_by: 3616
---

# _RESTRICTED_ALLOWED_TOOLS grants writes — use deny-list for read-only

Do not use `restricted=True` to restrict file writes when `_RESTRICTED_ALLOWED_TOOLS` in `src/agent_cli.py` contains the write tools — the emitted `--allowedTools` allowlist still grants them.

Use `disallowed_tools=READ_ONLY_DISALLOWED_TOOLS` instead, matching the `ResearchRunner` / `PlanReviewer` precedent.

**Why:** The allowlist makes the grant depend on CLI deny-vs-allow precedence, not an explicit deny.
