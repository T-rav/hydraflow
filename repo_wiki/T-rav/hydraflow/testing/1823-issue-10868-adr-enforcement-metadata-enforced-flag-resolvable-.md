---
id: 1823
topic: testing
source_issue: 10868
source_phase: plan
created_at: 2026-07-31T03:28:15.424935+00:00
status: superseded
corroborations: 1
superseded_by: 1927
---

# ADR enforcement metadata: enforced flag + resolvable Enforced-by path

Mark mechanically-enforced ADRs with `**Enforcement:** enforced` and a resolvable `**Enforced by:** pytest:...` path. For review-only ADRs, add a "Why no mechanical check" section.

- ADR-0025/0035 flip to enforced with pytest paths to their ratchet suites.
- ADR-0051 stays exempt with a rationale paragraph explaining no on-disk invariant exists.
- `test_adr_source_citations_exist.py` validates that `Enforced by:` paths resolve.
- State which ADR legs remain review guidance so later audits don't misread the flip as full mechanization.

**Why:** Without explicit metadata, audits can't distinguish mechanical checks from review guidance, leading to false confidence or re-debt creation.
