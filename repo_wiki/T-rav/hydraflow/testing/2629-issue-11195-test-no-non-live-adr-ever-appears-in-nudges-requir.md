---
id: 2629
topic: testing
source_issue: 11195
source_phase: plan
created_at: 2026-08-15T01:07:17.474008+00:00
status: active
corroborations: 1
---

# test_no_non_live_adr_ever_appears_in_nudges requires ≥1 non-live ADR

`test_no_non_live_adr_ever_appears_in_nudges` is only non-vacuous when at least one non-live ADR exists in the corpus.

- 11 non-live ADRs exist today: 3/6/13/20/31/33/36/39/40/55/91.
- Removing ADR-0013 from a fixture tree does not make this test vacuous.
- Do not add extra non-live ADRs to compensate; the existing count is sufficient.

**Why:** A vacuous "all nudges are live" assertion passes trivially and stops guarding against the regression it was written to catch.
