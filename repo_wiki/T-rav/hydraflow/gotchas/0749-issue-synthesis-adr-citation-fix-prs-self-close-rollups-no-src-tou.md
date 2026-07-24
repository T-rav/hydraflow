---
id: 0749
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.312280+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# ADR citation fix PRs self-close rollups: no src/ touch means no self-drift

A PR that only edits `docs/adr/*.md` to upgrade a bare citation to `:Symbol` granularity touches no `src/` files, so it introduces no new drift against itself — the triggering rollup issue (e.g. #10434) auto-closes on the next `RepoWikiLoop`/auditor tick after merge with no follow-up action needed.

**Why:** Confirms these fixes are self-contained and don't require a manual rollup-closing step, unlike code changes that can retrigger the same ADR's drift check.
