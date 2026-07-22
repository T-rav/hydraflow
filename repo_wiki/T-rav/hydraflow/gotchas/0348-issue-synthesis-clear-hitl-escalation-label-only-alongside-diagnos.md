---
id: 0348
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:02:32.375752+00:00
status: active
corroborations: 1
supersedes: 0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347
---

# Clear hitl-escalation label only alongside diagnose-failed

In `escalated_with_resolving_pr` (src/pr_manager.py), require BOTH `hitl-escalation` AND `diagnose-failed` labels before clearing `hydraflow-hitl-escalation` — don't rely on bare set-intersection truthiness.

Example: `corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, and `wiki_rot_detector_loop.py` file bare `hitl-escalation` plus their own `-stuck` label with no pipeline label backing it, and won't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
