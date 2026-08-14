---
id: 2021
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.771142+00:00
status: active
corroborations: 1
supersedes: 1913
---

# ADR section numbering: append next free, never renumber

Append new ADR sections at the next free number after the current last section; never renumber existing sections.

Example: ADR-0116 currently ends at §10, so the config-overrides decision is §11.

**Why:** Renumbering breaks cross-references scattered across other ADRs and docs that cite section numbers by value.
