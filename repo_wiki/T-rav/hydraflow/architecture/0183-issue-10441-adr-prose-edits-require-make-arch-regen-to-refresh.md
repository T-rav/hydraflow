---
id: 0183
topic: architecture
source_issue: 10441
source_phase: plan
created_at: 2026-07-24T10:43:53.902099+00:00
status: active
corroborations: 1
---

# ADR prose edits require `make arch-regen` to refresh `docs/arch/generated/adr_xref.md`

`docs/arch/generated/adr_xref.md` is derived from ADR source-file citations, so any edit to an ADR's prose (e.g. removing a bare `src/...` citation) must be followed by `make arch-regen` and the resulting diff committed alongside the ADR change. Skipping this leaves the ADR↔module xref rows stale and fails CI's arch-freshness check on the PR.
**Why:** the xref is a generated artifact, not hand-maintained — CI treats a stale `adr_xref.md` as a drift failure independent of the ADR text being correct.
