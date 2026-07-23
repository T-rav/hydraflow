---
source: feedback_workstream_fixes_over_loops.md
name: workstream-fixes-over-loops
description: 'Travis 2026-07-20: prefer fixing the workstream (pipeline phases/steps, existing loop intakes) over minting new caretaker loops — or do both; new-loop is not the default unit of automation'
status: promoted
issue: 10294
promoted_in: '#10294'
wontfix_reason: null
created: '2026-07-19'
---

Travis (2026-07-20, closing the step-away gap analysis): "workstream fixes instead of loops are also encouraged or in addition to, work as well."

**Why:** Each new caretaker loop costs seven-checkpoint wiring, its own kill-switch, fitness declaration, scenario shims, and a permanent slot in the supervise list — and it runs OUTSIDE the flow of work, polling for what a workstream step could have handled in-line. #10027 is the cautionary example, not a success model: the 2026-07-20 operator steer specced `PrRedRepairLoop` as an INTAKE on PRUnsticker's existing CI-fix dispatch ("zero new loops, one new intake + one classifier"), but what actually shipped (#10124 / #10157) was a full standalone `PrRedRepairLoop` — its own `BaseBackgroundLoop` subclass, supervise slot, kill-switch, state mixin, and `functional_areas.yml` entry; only the word "intake" survived, in a docstring. The consolidation was NOT done. #10318 assessed the retro-fold and found it is a behavior-changing re-implementation (a proactive repo-wide settled-red scan + infra-flake rerun that PRUnsticker's HITL-gated dispatch structurally cannot host), so `PrRedRepairLoop` is accepted as-is (grandfathered in `tests/architecture/test_functional_area_coverage.py::test_new_loops_justify_workstream_alternative`) rather than force-merged. The lesson: name the workstream host up front AND hold the implementation to it, or the loop-minting default wins by ~30 hours of drift. Similarly [[backlog-to-loop-reflection]]'s "spec a resolver" should be read as "spec a resolver *in the workstream where the problem occurs*" first.

**How to apply:** When closing an automation gap, ask in order: (1) can an existing PHASE (triage/plan/implement/review/merge) own this as a step or gate? (2) can an existing loop own it as a new intake/classifier? (3) only then, a new caretaker loop — reserved for genuinely cross-cutting cadence work with no natural host (e.g. GateHealthLoop's weekly statistics) or externally-hosted needs (#10009 liveness, which must outlive the process). When filing design issues, name the intended HOST explicitly so the factory doesn't default to loop-minting.
