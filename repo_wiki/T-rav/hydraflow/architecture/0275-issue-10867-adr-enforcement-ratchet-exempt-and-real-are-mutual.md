---
id: 0275
topic: architecture
source_issue: 10867
source_phase: plan
created_at: 2026-07-31T03:20:17.216714+00:00
status: active
corroborations: 1
---

# ADR enforcement ratchet: exempt and REAL are mutually exclusive

When promoting an Accepted ADR from exempt to enforced, the ratchet forbids both states simultaneously. Remove the `- ADR-NNNN:` entry from `docs/standards/adr_enforcement/exemptions.md` and add the number to `resolved` in `tests/architecture/adr_enforcement_baseline.json`. Never modify `baseline_snapshot` — it is a frozen set of 12 ids. The gate `tests/architecture/test_adr_enforcement_ratchet.py` fails if `resolved` and the exemption list overlap.

**Why:** The ratchet encodes one-way debt reduction; exempt+REAL is a contradictory state.
