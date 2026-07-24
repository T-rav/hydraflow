---
id: 0402
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.282712+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Clear hitl-escalation label only alongside diagnose-failed

In `escalated_with_resolving_pr` (src/pr_manager.py), require BOTH `hitl-escalation` AND `diagnose-failed` labels before clearing `hydraflow-hitl-escalation` — don't rely on bare set-intersection truthiness.

Example: `corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, and `wiki_rot_detector_loop.py` file bare `hitl-escalation` plus their own `-stuck` label with no pipeline label backing it, and won't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
