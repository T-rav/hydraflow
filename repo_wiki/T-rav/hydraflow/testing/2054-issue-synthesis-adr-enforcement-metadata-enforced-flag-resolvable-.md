---
id: 2054
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.034488+00:00
status: superseded
corroborations: 1
supersedes: 1927
superseded_by: 2183
---

# ADR enforcement metadata: enforced flag + resolvable Enforced-by path

Mark mechanically-enforced ADRs with `**Enforcement:** enforced` and a resolvable `**Enforced by:** pytest:...` path. For review-only ADRs, add a "Why no mechanical check" section. State which ADR legs remain review guidance so later audits don't misread the flip as full mechanization.

Example: ADR-0025/0035 flip to enforced with pytest paths to their ratchet suites. ADR-0051 stays exempt with a rationale paragraph. `test_adr_source_citations_exist.py` validates Enforced-by paths resolve.

**Why:** Without explicit metadata, audits can't distinguish mechanical checks from review guidance, leading to false confidence or re-debt creation.
