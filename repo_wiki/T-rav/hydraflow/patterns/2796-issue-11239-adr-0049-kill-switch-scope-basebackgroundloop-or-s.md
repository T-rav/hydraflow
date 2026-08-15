---
id: 2796
topic: patterns
source_issue: 11239
source_phase: plan
created_at: 2026-08-15T09:47:55.217040+00:00
status: active
corroborations: 1
---

# ADR-0049 kill-switch scope: BaseBackgroundLoop or subprocess runners only

ADR-0049 kill-switch applies only to new `BaseBackgroundLoop` subclasses or subprocess-spawning runners. Git/gh calls routed through a `BotPRPort` adapter into `auto_pr` do not trigger it — no raw `subprocess`/`gh` in non-adapter files. **Why:** Knowing the scope prevents over-engineering a kill-switch for a synchronous Port call or bypassing it with raw subprocess in application code.
