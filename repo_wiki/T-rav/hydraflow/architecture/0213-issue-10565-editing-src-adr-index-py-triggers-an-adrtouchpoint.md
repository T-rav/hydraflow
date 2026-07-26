---
id: 0213
topic: architecture
source_issue: 10565
source_phase: plan
created_at: 2026-07-25T23:03:04.264311+00:00
status: stale
corroborations: 1
stale_reason: source issue #10565 closed
---

# Editing src/adr_index.py triggers an AdrTouchpointAuditorLoop rollup (ADR-0100 bare-cites it)

ADR-0100 bare-cites `src/adr_index.py` and is not on the shared-infra allowlist (`_SHARED_INFRA_MODULES`), so any change there is expected to trigger an `AdrTouchpointAuditorLoop` rollup post-merge. `Skip-ADR:` no longer exists in `src/`, so close the rollup with a one-line implementation-level explanation instead of the old skip marker.

**Why:** without this expectation, the post-merge rollup looks like a new regression instead of a known, allowlist-driven auditor artifact.
