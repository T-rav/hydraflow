---
id: 2385
topic: testing
source_issue: 11088
source_phase: plan
created_at: 2026-08-14T08:31:19.200128+00:00
status: superseded
corroborations: 1
superseded_by: 2573
---

# Reuse catalog_fake_methods as a coverage ratchet over tests/

Use `catalog_fake_methods` + `FakeCoverageAuditorLoop._grep_scenario_for_helper` as a regression pin asserting every FakeLLM `test-helper` bucket method is invoked by at least one file under `tests/`.

- The pin must resolve `tests/` and the fakes package from the repo root, not CWD.
- A future FakeLLM helper added without coverage fails the pin by design — this is the ratchet, not flakiness.

**Why:** Keeps the auditor's own detector honest against the real test tree, preventing silent drift between the catalog and actual coverage.
