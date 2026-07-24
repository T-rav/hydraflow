---
id: 0688
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.486913+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# ADR citation fix PRs self-close rollups: no src/ touch means no self-drift

A PR that only edits `docs/adr/*.md` to upgrade a bare citation to `:Symbol` granularity touches no `src/` files, so it introduces no new drift against itself — the triggering rollup issue (e.g. #10434) auto-closes on the next `RepoWikiLoop`/auditor tick after merge with no follow-up action needed.

**Why:** Confirms these fixes are self-contained and don't require a manual rollup-closing step, unlike code changes that can retrigger the same ADR's drift check.
