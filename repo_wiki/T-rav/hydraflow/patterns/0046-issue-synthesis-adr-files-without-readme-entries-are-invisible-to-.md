---
id: 0046
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.320983+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# ADR files without README entries are invisible to tooling

Every ADR file in `docs/adr/` must have a corresponding row in `docs/adr/README.md` to be canonically referenceable.

Example: adding `docs/adr/0055-new-decision.md` requires a matching `| 0055 | New Decision | Accepted |` row in README.

**Why:** `scan_adr_directory()` builds its index from README rows; a file without a row is silently skipped by drift detection and cross-reference tooling.
