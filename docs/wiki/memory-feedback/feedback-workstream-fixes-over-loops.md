---
source: feedback_workstream_fixes_over_loops.md
name: workstream-fixes-over-loops
description: 'Travis 2026-07-20: prefer fixing the workstream (pipeline phases/steps, existing loop intakes) over minting new caretaker loops — or do both; new-loop is not the default unit of automation'
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-07-19'
---

Travis (2026-07-20, closing the step-away gap analysis): "workstream fixes instead of loops are also encouraged or in addition to, work as well."

**Why:** Each new caretaker loop costs seven-checkpoint wiring, its own kill-switch, fitness declaration, scenario shims, and a permanent slot in the supervise list — and it runs OUTSIDE the flow of work, polling for what a workstream step could have handled in-line. The #10027 consolidation is the model: what was specced as `PrRedRepairLoop` became an INTAKE on PRUnsticker's existing CI-fix dispatch plus a pre-step retrier — zero new loops, same coverage, reuses the troubleshooting-pattern memory the workstream already accumulates. Similarly [[backlog-to-loop-reflection]]'s "spec a resolver" should be read as "spec a resolver *in the workstream where the problem occurs*" first.

**How to apply:** When closing an automation gap, ask in order: (1) can an existing PHASE (triage/plan/implement/review/merge) own this as a step or gate? (2) can an existing loop own it as a new intake/classifier? (3) only then, a new caretaker loop — reserved for genuinely cross-cutting cadence work with no natural host (e.g. GateHealthLoop's weekly statistics) or externally-hosted needs (#10009 liveness, which must outlive the process). When filing design issues, name the intended HOST explicitly so the factory doesn't default to loop-minting.
