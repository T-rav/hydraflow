---
id: 1455
topic: testing
source_issue: 10757
source_phase: plan
created_at: 2026-07-28T00:08:58.218752+00:00
status: active
corroborations: 1
---

# Keep assess_topic_coverage parameter names inside the probe's alias table

Rule: `assess_topic_coverage(plan, topic_dir)` parameter names must match the regression probe's alias table exactly: `plan`/`topic_dir`/`topic`/`tracked_root`/`repo`. The probe calls the entry point with aliased kwargs; an off-table name makes it return `<unmappable>` and the test stays red despite a correct implementation.

**Why:** The alias table is a deliberate indirection that prevents the probe from being weakened to match implementation drift — renaming a parameter silently breaks the guard.
