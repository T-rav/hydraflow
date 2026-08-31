---
id: 2788
topic: testing
source_issue: 11548
source_phase: plan
created_at: 2026-08-30T10:39:26.773625+00:00
status: active
corroborations: 1
---

# suite_hygiene.yaml must be regen'd last, from the branch's own merge base

The `disturbance/baselines/suite_hygiene.yaml` marks drift if regenerated against a foreign HEAD. Lock them last:

- P0: assert the sensor at the branch's merge base matches the roster (e.g. 401 copies / 19 dups).
- Run `python scripts/regen_suite_hygiene_baseline.py --reason "..."` only after P1–P4.
- Never hand-edit; the file is written by the regen script only.

**Why:** Another PR merging mid-batch would launder its copies into the marks, hiding pre-existing slack (#8460 blast radius).
