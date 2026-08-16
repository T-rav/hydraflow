---
id: 4053
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:41:45.062071+00:00
status: active
corroborations: 1
supersedes: 3906
---

# _RESTRICTED_ALLOWED_TOOLS grants writes — use deny-list for read-only

Do not use `restricted=True` to restrict file writes when `_RESTRICTED_ALLOWED_TOOLS` in `src/agent_cli.py` contains the write tools — the emitted `--allowedTools` allowlist still grants them. Use `disallowed_tools=READ_ONLY_DISALLOWED_TOOLS` instead, matching the `ResearchRunner` / `PlanReviewer` precedent.

**Why:** The allowlist makes the grant depend on CLI deny-vs-allow precedence, not an explicit deny.
