---
id: 3317
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:49.043726+00:00
status: active
corroborations: 1
supersedes: 3184
---

# ADR-0049 kill-switch scope: BaseBackgroundLoop or subprocess runners only

ADR-0049 kill-switch applies only to new `BaseBackgroundLoop` subclasses or subprocess-spawning runners. Git/gh calls routed through a `BotPRPort` adapter into `auto_pr` do not trigger it — no raw `subprocess`/`gh` in non-adapter files.

**Why:** Knowing the scope prevents over-engineering a kill-switch for a synchronous Port call or bypassing it with raw subprocess in application code.
