---
id: 0642
topic: gotchas
source_issue: 10443
source_phase: plan
created_at: 2026-07-24T11:10:04.090365+00:00
status: superseded
corroborations: 1
superseded_by: 0643
---

# PRs editing docs/adr/*.md self-cover that ADR via _adr_file_in_diff

When a PR's diff includes `docs/adr/00NN-*.md` itself, `_adr_file_in_diff` treats ADR NN as self-covered for that diff, so a citation/content fix to an ADR won't spuriously drift itself in the same PR. Relevant when writing regression tests for ADR-drift fixes (e.g. issue #10443's fix to ADR-0055:107) — the test only needs to check a *separate* file-only diff (touching `src/base_background_loop.py` alone) to reproduce the drift, not the combined ADR+code diff. **Why:** avoids writing a self-contradicting regression test that expects drift on a diff the auditor already exempts.
