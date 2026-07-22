---
id: 0337
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.503862+00:00
status: active
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
---

# Clear hitl-escalation label only alongside diagnose-failed

In `src/pr_manager.py`'s `escalated_with_resolving_pr` drift check, don't clear `hydraflow-hitl-escalation` on bare set-intersection truthiness — require BOTH `hitl-escalation` AND `diagnose-failed` before clearing.

Example: `corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, and `wiki_rot_detector_loop.py` file bare `hitl-escalation` plus their own `-stuck` label with no pipeline label backing it, and won't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
