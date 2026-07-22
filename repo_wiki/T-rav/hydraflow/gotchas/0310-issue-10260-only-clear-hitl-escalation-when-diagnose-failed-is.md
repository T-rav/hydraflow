---
id: 0310
topic: gotchas
source_issue: 10260
source_phase: review
created_at: 2026-07-22T11:54:54.586661+00:00
status: active
corroborations: 1
---

# Only clear hitl-escalation when diagnose-failed is also present

In `src/pr_manager.py`'s `escalated_with_resolving_pr` drift check, don't clear `hydraflow-hitl-escalation` on bare set-intersection truthiness — require BOTH `hitl-escalation` AND `diagnose-failed` before clearing. Other loops (`corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, `wiki_rot_detector_loop.py`) file bare `hitl-escalation` + their own `-stuck` label with no pipeline label backing it, and don't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
