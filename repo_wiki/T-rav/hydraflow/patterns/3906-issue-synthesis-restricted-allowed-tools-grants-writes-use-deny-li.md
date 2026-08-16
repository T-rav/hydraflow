---
id: 3906
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:58.324128+00:00
status: active
corroborations: 1
supersedes: 3761
---

# _RESTRICTED_ALLOWED_TOOLS grants writes — use deny-list for read-only

Do not use `restricted=True` to restrict file writes when `_RESTRICTED_ALLOWED_TOOLS` in `src/agent_cli.py` contains the write tools — the emitted `--allowedTools` allowlist still grants them. Use `disallowed_tools=READ_ONLY_DISALLOWED_TOOLS` instead, matching the `ResearchRunner` / `PlanReviewer` precedent.

**Why:** The allowlist makes the grant depend on CLI deny-vs-allow precedence, not an explicit deny.
