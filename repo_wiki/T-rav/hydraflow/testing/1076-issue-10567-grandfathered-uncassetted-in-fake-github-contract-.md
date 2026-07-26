---
id: 1076
topic: testing
source_issue: 10567
source_phase: plan
created_at: 2026-07-25T23:37:32.613871+00:00
status: superseded
corroborations: 1
superseded_by: 1085
---

# GRANDFATHERED_UNCASSETTED in fake_github contract test only shrinks

In tests/trust/contracts/test_fake_github_contract.py, `GRANDFATHERED_UNCASSETTED` is a legacy allowlist for adapter methods missing a cassette — never add a new method to it to unblock `test_adapter_surface_fully_cassetted`. New Port methods must ship a real cassette (e.g. tests/trust/contracts/cassettes/github/get_pr_labels.yaml) instead.
**Why:** treating the grandfather list as growable defeats ADR-0047's cassette-coverage ratchet and lets uncassetted adapters back in.
