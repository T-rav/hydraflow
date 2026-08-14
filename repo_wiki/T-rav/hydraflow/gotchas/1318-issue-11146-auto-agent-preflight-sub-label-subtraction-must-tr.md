---
id: 1318
topic: gotchas
source_issue: 11146
source_phase: plan
created_at: 2026-08-14T15:08:46.027492+00:00
status: active
corroborations: 1
---

# auto_agent_preflight sub-label subtraction must track queue label

In `src/auto_agent_preflight_loop.py`, the queue label is subtracted from label sets to derive the playbook sub-label. Every subtraction site must use the config-resolved `hitl_queue_label`, not the old literal.

- Poll, closed-issue reconcile, widened-intake exclusion, and both `sub_labels` subtractions are all affected.
- Missing one subtraction routes every escalation to `_default`.

**Why:** A single missed subtraction site causes all escalations to fall through to the default playbook after a rename — silent, no error, just wrong routing.
