---
id: 0762
topic: gotchas
source_issue: 10464
source_phase: plan
created_at: 2026-07-24T15:39:21.687885+00:00
status: active
corroborations: 1
---

# TermProposerLoop can break CI via paraphrase collisions with wiki prose

`TermProposerLoop` auto-adds `docs/wiki/terms/*.md` drafts whose aliases can duplicate phrasing already present as prose in files like `gotchas.md` or `dark-factory.md`. This trips `test_paraphrase_lint_runs_against_live_wiki` and fails both Tests and Coverage jobs, which roll up into a red CI Gate on the next `rc/*` promotion PR. Example: alias `"credit exhaustion"` collided with prose in `dark-factory.md` §2.2, blocking issue #10464's RC promotion. **Why:** the proposer loop runs autonomously on a cadence — an unguarded validator lets it silently regress the ubiquitous-language lint on every tick.
