---
id: 0821
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:10.120139+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# TermProposerLoop can break CI via paraphrase collisions with wiki prose

`TermProposerLoop` auto-adds `docs/wiki/terms/*.md` drafts whose aliases can duplicate phrasing already present as prose elsewhere in the wiki (e.g. `gotchas.md`, `dark-factory.md`), tripping `test_paraphrase_lint_runs_against_live_wiki` and turning CI red on the next `rc/*` promotion PR.

Example: alias "credit exhaustion" collided with prose in `dark-factory.md` §2.2, blocking issue #10464's RC promotion.

**Why:** the proposer loop runs autonomously on a cadence — an unguarded validator lets it silently regress the ubiquitous-language lint on every tick.
