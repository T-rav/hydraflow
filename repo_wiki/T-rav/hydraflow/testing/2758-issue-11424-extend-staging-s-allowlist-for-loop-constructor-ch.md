---
id: 2758
topic: testing
source_issue: 11424
source_phase: review
created_at: 2026-08-18T09:01:27.985887+00:00
status: active
corroborations: 1
---

# Extend staging's allowlist for loop constructor checks, don't recreate

When adding loop constructor wiring checks, extend `tests/scenarios/catalog/test_collaborator_wiring.py` on staging rather than creating a new file. Staging's version uses a generic AST-derived check over every loop constructor plus an audited allowlist — do not replace it with a hardcoded site-specific table.

If a site is missing from staging's allowlist, add a row there instead.

**Why:** A hardcoded table regresses the generality of the AST-derived guard and creates maintenance burden when new loops are added.
