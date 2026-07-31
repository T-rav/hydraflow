---
id: 2047
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.991516+00:00
status: superseded
corroborations: 1
supersedes: 1920
superseded_by: 2176
---

# Amend ADRs same-commit as src/ deletions they cite

When deleting `src/` files bare-cited by an Accepted/enforced ADR, amend the ADR in the same commit as the deletion.

Example: `tests/test_adr_citation_conformance.py::test_no_unresolved_adr_citations` red-lines mid-branch if `src/adr_drift_resolver_loop.py` is deleted before ADR-0056 decision point 8 is amended. ADR-0055 bare-cites five `src/telemetry/*.py` files.

**Why:** The conformance test treats any ADR citation to a non-existent file as a violation; splitting deletion and amendment across commits breaks the branch for any intermediate CI run.
