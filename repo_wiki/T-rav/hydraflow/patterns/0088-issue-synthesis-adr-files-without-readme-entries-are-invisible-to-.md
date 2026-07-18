---
id: 0088
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.447618+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# ADR files without README entries are invisible to tooling

Every ADR file in `docs/adr/` must have a corresponding row in `docs/adr/README.md` to be canonically referenceable.

Example: adding `docs/adr/0055-new-decision.md` requires a matching `| 0055 | New Decision | Accepted |` row in README.

**Why:** `scan_adr_directory()` builds its index from README rows; a file without a row is silently skipped by drift detection and cross-reference tooling.
