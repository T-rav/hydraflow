---
id: 2511
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.732492+00:00
status: active
corroborations: 1
supersedes: 2321
---

# Amend ADRs same-commit as src/ deletions they cite

When deleting `src/` files bare-cited by an Accepted/enforced ADR, amend the ADR in the same commit as the deletion.

Example: `tests/test_adr_citation_conformance.py::test_no_unresolved_adr_citations` red-lines mid-branch if `src/adr_drift_resolver_loop.py` is deleted before ADR-0056 decision point 8 is amended.

**Why:** The conformance test treats any ADR citation to a non-existent file as a violation; splitting deletion and amendment across commits breaks the branch for any intermediate CI run.
