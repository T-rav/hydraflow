---
id: 2923
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.548864+00:00
status: superseded
corroborations: 1
supersedes: 2796
superseded_by: 3050
---

# ADR-0049 kill-switch scope: BaseBackgroundLoop or subprocess runners only

ADR-0049 kill-switch applies only to new `BaseBackgroundLoop` subclasses or subprocess-spawning runners. Git/gh calls routed through a `BotPRPort` adapter into `auto_pr` do not trigger it — no raw `subprocess`/`gh` in non-adapter files.

**Why:** Knowing the scope prevents over-engineering a kill-switch for a synchronous Port call or bypassing it with raw subprocess in application code.
