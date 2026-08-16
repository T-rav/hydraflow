---
id: 3454
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:58.209598+00:00
status: superseded
corroborations: 1
supersedes: 3317
superseded_by: 3601
---

# ADR-0049 kill-switch scope: BaseBackgroundLoop or subprocess runners only

ADR-0049 kill-switch applies only to new `BaseBackgroundLoop` subclasses or subprocess-spawning runners. Git/gh calls routed through a `BotPRPort` adapter into `auto_pr` do not trigger it — no raw `subprocess`/`gh` in non-adapter files.

**Why:** Knowing the scope prevents over-engineering a kill-switch for a synchronous Port call or bypassing it with raw subprocess in application code.
