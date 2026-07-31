---
id: 1096
topic: patterns
source_issue: 10872
source_phase: plan
created_at: 2026-07-31T05:36:11.799875+00:00
status: superseded
corroborations: 1
superseded_by: 1164
---

# ADR section numbering: append next free, never renumber

Append new ADR sections at the next free number after the current last section; never renumber existing sections. ADR-0116 currently ends at §10, so the config-overrides decision is §11. **Why:** Renumbering breaks cross-references scattered across other ADRs and docs that cite section numbers by value.
