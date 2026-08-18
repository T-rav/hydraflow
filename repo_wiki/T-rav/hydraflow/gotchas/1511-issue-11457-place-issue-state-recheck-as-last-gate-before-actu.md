---
id: 1511
topic: gotchas
source_issue: 11457
source_phase: plan
created_at: 2026-08-18T12:04:53.781973+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Place issue-state recheck as last gate before actuator in _build_implement_flow

Rule: new gates in `ImplementPhase._build_implement_flow` go after `no-progress-abort` and before `build`. `decompose`'s existing-PR shortcut and attempt cap run first; the issue-state recheck is the last gate before the actuator.

Example: DAG walk is `decompose -> no-progress-abort -> issue-state -> build`, with `Edge("issue-state", "done", when=_flow_stopped)`.

**Why:** Re-checking before earlier gates wastes a read; re-checking after `build` wastes a full build on a closed issue.
