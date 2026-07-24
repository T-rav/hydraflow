---
id: 0638
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.729900+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# ADR citation fix PRs self-close rollups: no src/ touch means no self-drift

A PR that only edits `docs/adr/*.md` to upgrade a bare citation to `:Symbol` granularity touches no `src/` files, so it introduces no new drift against itself — the triggering rollup issue (e.g. #10434) auto-closes on the next `RepoWikiLoop`/auditor tick after merge with no follow-up action needed.

**Why:** confirms these fixes are self-contained and don't require a manual rollup-closing step, unlike code changes that can retrigger the same ADR's drift check.
