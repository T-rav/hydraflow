---
id: 1227
topic: gotchas
source_issue: 10870
source_phase: plan
created_at: 2026-07-31T06:08:36.407854+00:00
status: active
corroborations: 1
---

# Auto-agent prompt rendering splits into two families

Templates in `prompts/auto_agent/` render via two distinct mechanisms. 17 templates use `preflight.runner.render_prompt` (`str.format` over 12 keyword fields plus the `{{> _envelope.md}}` include). 2 templates (`pr_red_fix.md`, `sandbox_fix.md`) are read directly by `PrRedRepairLoop` and `SandboxFailureFixerLoop` using `str.replace` on UPPER_CASE tokens.

**Why:** `str.replace` UPPER_CASE tokens will `KeyError` if passed through `str.format`; mixing the two mechanisms crashes escalation-time rendering in production.
