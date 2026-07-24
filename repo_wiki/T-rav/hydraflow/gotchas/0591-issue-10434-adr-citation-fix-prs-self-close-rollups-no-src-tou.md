---
id: 0591
topic: gotchas
source_issue: 10434
source_phase: plan
created_at: 2026-07-24T10:19:32.942816+00:00
status: active
corroborations: 1
---

# ADR citation fix PRs self-close rollups: no src/ touch means no self-drift

A PR that only edits `docs/adr/*.md` to upgrade a bare citation to `:Symbol` granularity touches no `src/` files, so it introduces no new drift against itself — the triggering rollup issue (e.g. #10434) auto-closes on the next `RepoWikiLoop`/auditor tick after merge with no follow-up action needed.

**Why:** confirms these fixes are self-contained and don't require a manual rollup-closing step, unlike code changes that can retrigger the same ADR's drift check.
