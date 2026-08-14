---
id: 1815
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.167371+00:00
status: superseded
corroborations: 1
supersedes: 1719
superseded_by: 1913
---

# ADR section numbering: append next free, never renumber

Append new ADR sections at the next free number after the current last section; never renumber existing sections.

Example: ADR-0116 currently ends at §10, so the config-overrides decision is §11.

**Why:** Renumbering breaks cross-references scattered across other ADRs and docs that cite section numbers by value.
