---
id: 0317
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.192603+00:00
status: active
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
---

# Clear hitl-escalation label only alongside diagnose-failed

In `src/pr_manager.py`'s `escalated_with_resolving_pr` drift check, don't clear `hydraflow-hitl-escalation` on bare set-intersection truthiness — require BOTH `hitl-escalation` AND `diagnose-failed` before clearing.

Example: `corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, and `wiki_rot_detector_loop.py` file bare `hitl-escalation` plus their own `-stuck` label with no pipeline label backing it, and won't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
