# ADR-0149: The per-change artifact chain lives in the repo

- **Status:** Proposed
- **Date:** 2026-09-04
- **Enforcement:** unenforced
- **Binds:** factory
- **Extends:** [ADR-0032](0032-per-repo-wiki-knowledge-base.md) (which moved the wiki out of `.hydraflow/` runtime state and into git-tracked `docs/`), [ADR-0143](0143-paaa-governance-model-and-the-decision-seam.md) (which made Artifacts a layer and gave `charter.yaml` a required-artifacts field)
- **Related:** [ADR-0113](0113-adr-lineage-precedent-and-divergence.md) (the precedent/divergence discipline this record follows), [ADR-0044](0044-hydraflow-principles.md) (P10, the test-and-evidence obligations a committed chain would make checkable), [ADR-0121](0121-rails-manifest-and-drift-caretaker.md) (the drift caretaker that would audit a repo's declared chain)

**Enforced by:** nothing yet — deliberately.

This ADR records a decision whose mechanism does not exist. An `Accepted` status
would claim a binding this repo does not have, and the enforcement ratchet
(`adr_conformance.classify_adr_enforcement`) would correctly class it `MISSING`.
It becomes `Accepted` when P1 lands and the presence gate in P4 can be cited
here. Recording the decision before building it is the point — the shape was
ruled on 2026-09-03 and the rulings should not live only in an issue thread.

## Context

Today the only committed artifact per change is the **diff**. Everything else
that describes the change lives in runtime state on one host, subject to GC:

| artifact | written to | read by |
|---|---|---|
| intent | the GitHub issue body | everything, via the API |
| plan | `.hydraflow/plans/issue-N.md` + an issue comment | seven `plans_dir` read sites, all disk |
| acceptance criteria | `.hydraflow/verification/issue-N.md` | review |
| approval record | `<repo_data_root>/audit/approval_records.jsonl` (CH-2) | the evidence-pack compiler |
| evidence pack | `<repo_data_root>/evidence/rc-*/` (CH-4) | humans; `RunsGCLoop` |
| transcript | `.hydraflow/logs/` | nobody, after the fact |

The consequence is structural rather than aesthetic: **a gate cannot diff a PR
against the plan it was built from, because the gate cannot see the plan.** Every
alignment question — did the diff do what the plan said, did the change touch
files the plan never named — is unanswerable by a machine, not because it is
hard but because the input is not in the repository.

ADR-0032 already made this move once, for the wiki, and for the same reason.

## Decision

**Every change leaves a version-controlled chain in the managed repo**, on the
change's own branch, so it lands in the same PR as the diff:

```
docs/changes/<issue-N>/
  intent.md     # the issue body, snapshotted at plan time
  plan.md
  criteria.md
  evidence.md
```

`evidence.md` is a **receipt, not a binder**: approval-record id and chain
position, approver identity and role, the change class the gate assigned and
whether it required a human, review verdict ids and reviewing model family,
evidence-pack path and per-file digests, CI run ids. The hash-chained JSONL
streams and RC pack directories stay where they are and are cross-referenced by
digest.

### Two rulings, made 2026-09-03, recorded here

**1. Human review is a per-class, per-repo configuration — and the shipped
template names no class.** Self-approval through the gate stays the default for
every class, harness self-modification included. A repo may name classes
requiring an `operator` approver; the template ships none.

The question of whether the charter's own `policy:` section should be such a
class was put and answered **no**. The reasoning is that its protection is
already structural: editing `charter.yaml` is self-modification class and
demands an independent fail-closed verdict (#12115), it is out of reach of the
unsticker's standing grant (#12129), and the review verdict and CH-2 record
apply as they do to any change.

**2. Retention is quarterly compaction.** Live change directories stay flat;
each quarter folds into `docs/changes/archive/YYYY-Qn/`. At factory throughput
(~1,700 merged PRs in four months) keeping every directory flat forever reaches
~5,000 a year, and `docs/changes/` becomes the largest tree in the repo. A move
is not a delete, so `git log --follow` still reaches an archived change's intent
and plan.

**The second ruling constrains the first artifact.** Compaction rewrites paths,
so anything cross-referencing a change directory *by path* breaks the first time
that change is archived. `evidence.md` referencing records by id and digest was
already the design (the AI-native SDLC playbook's option 3); it is now
non-negotiable rather than stylistic. The same constraint binds the gate — it
must locate a change's files relative to the change under test — and the
metrics, which must follow the file rather than memoise a path.

## Divergence

**Precedent:** software traceability (Gotel & Finkelstein 1994); the AI-native
SDLC playbook (Anthropic, 2026-08-21) for the committed chain, its
cross-reference-by-digest option, and its Stage 3 metric "alignment between
merged diff and committed `plan.md`"; MinimumCD's immutable artifact;
change control with risk-classed approval (ITIL standard/normal/emergency).
In-house: ADR-0032, and CH-3's existing act-vs-ask classes.

**Divergence — on the chain:** the playbook's chain is written and approved by
humans at every hop, so *inspection* is the control. Here the chain is written by
agents and read by agents at execution time, and a committed plan is not
trustworthy by inspection. It is digest-checked against the CH-1 record the
planner appended, which the agent cannot rewrite, and the diff is scope-checked
against the plan. Receipts: the self-modification fail-closed class (#10371) and
the adversarial scope-check holdouts (`tests/trust/adversarial/cases/holdout-scope-check-*`).

**Divergence — on approval:** classic change control puts a second *person* on
every change. Here the second party is the gate, structurally, for every class by
default; a person appears only where the repo's configuration names the class,
and the configuration is itself a committed, gate-checked artifact. Receipt: the
factory map's PR-only write path, review as its own stage, out-of-family verdicts
for risky changes, and escalation stepping aside to a person.

## Consequences

- A gate can finally ask "does this diff match the plan it was built from",
  because both are in the same commit range.
- Three metrics fall out mechanically rather than needing instrumentation:
  rework (commits to `plan.md` after the first implementation commit), alignment
  (files touched outside the plan's named files), time-to-plan (`intent.md` to
  `plan.md` commit timestamps).
- `charter.yaml` gains a declaration of which chain files a repo requires, and
  the ADR-0121 drift caretaker audits it.
- Repo mass grows by one directory per change, bounded by quarterly compaction.
- **The gate must be staged.** Presence first, report-only; digest match and
  diff-vs-plan scope after its findings are judged — the same staging as vitals
  (#10838) and setpoints (#10824). A scope gate armed on day one would block
  changes for disagreeing with a plan format nobody has written against yet.

## Status note

Unbuilt. `docs/changes/` does not exist, no source reads it, and this record is
`Proposed` for exactly that reason. The build is the remaining work on #12114
and is not scheduled — it is deliberately deferred behind a new project build,
where a chain written from the first change is cheaper than one retrofitted onto
1,700.
