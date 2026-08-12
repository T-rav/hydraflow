# Consoles of Personas — chartered review chambers for HydraFlow-format repos

**Pattern origin:** harvestd, 2026-07-31 (`T-rav/harvestd` — `agents/` personas +
`console/` with a general contract and three chambers + `console/decisions/`
with ten founding records). This document generalizes that reference
implementation into a methodology any HydraFlow-format repo can stamp
(`make stamp DIR=… AGENTS_CONSOLE=1` adds the skeleton; see
[Onboarding](onboarding-hydraflow-format-repos.md)).

**What it is:** a governed way to get *multi-perspective review with recorded
verdicts* out of generative agents — personas as versioned contracts, chambers
with bounded decision rights, ADR-style decision records, and calibration that
treats each persona as an instrument to be measured. **What it is not:** a
replacement for the factory's judge/eval machinery. This is the persona-scale
application of the judge-independence findings (same-substrate seats, proper
scoring, escape-ledger ground truth) — the chambers *feed* the same evidence
discipline, they do not bypass it.

## Layer 1 — Personas as versioned contracts

A persona is a **file, not a vibe**: one contract per persona, versioned in
git, with frontmatter that makes its authority machine-checkable.

- **Identity**: who this persona is, what expertise it simulates, what it
  systematically looks for — and what it deliberately ignores (scope is part
  of the contract).
- **Verdict format**: the exact structured output the persona must emit
  (verdict token + findings + confidence). A persona whose output cannot be
  parsed cannot be calibrated, and an uncalibratable persona is noise.
- **`authority:` frontmatter**: what this persona may *decide* vs merely
  *advise* on. Default: advise-only.
- **`feeds:` frontmatter**: which chamber(s) consume this persona's verdicts.
  A persona feeding nothing is dead weight; the directory listing exposes it.
- **Kernel boundaries**: what the persona may never do regardless of prompt
  drift — the entrenched clauses (no merge authority, no money, no
  self-modification of its own contract).

## Layer 2 — Chambers: chairs, seats, bounded decision rights

A chamber is a chartered panel with a **chair**, **seats** (personas), and an
explicit, bounded decision right (the harvestd reference chartered three:
design, architecture, ops).

- **Seat verdicts before chair consolidation.** Every seat renders its own
  verdict *first*; the chair consolidates *after*. A chair that drafts before
  seats report is an echo chamber with extra steps.
- **Disagreement escalates by name — it is never averaged.** A 2–1 split is
  reported as "X and Y hold A; Z holds B because…", not as "the chamber
  leans A". Averaging launders the minority signal that calibration needs.
- **No chamber creates.** Chambers review, adjudicate, and record; generative
  work happens outside and is *brought to* the chamber.
- **No chamber holds money or merge authority.** Decision rights are bounded
  to verdicts-on-the-record; enactment stays with the factory's gates and the
  human floor (the same propose-vs-commit line as ADR-0132).

## Layer 3 — Decision records: no committed record, no verdict

Every adjudication produces **one numbered, ADR-style file** in the chamber's
`decisions/` directory. The chair's closing duty is the commit: **a verdict
that is not committed to the record did not happen.** The directory listing is
the index — no hand-maintained tables (they drift; `ls` doesn't). This is the
institutional-continuity discipline applied at persona scale: a successor
reconstructs the chamber's precedent from the records, not from anyone's
memory.

## Layer 4 — Calibration: the persona is an instrument; measure it

- **Finding-survival rate per persona.** Track what fraction of each persona's
  findings survive downstream scrutiny (fixes shipped, escapes confirmed,
  chair adoption). This is the persona's precision series.
- **Fatigue budget.** A persona whose findings stop surviving is a
  **miscalibrated instrument**, not a hard worker: retire, re-contract, or
  re-scope it. Findings-per-review without survival is noise production.
- **Drift rule.** Divergence between a persona's *behavior* and its *file* is
  itself a finding. The contract is the spec; behavior drift means either the
  contract or the runtime is wrong, and silence about it corrupts the record.
- **Vote-counting honesty (mandatory language).** Seats running on the same
  model substrate are **not independent votes**: N same-substrate seats
  deliver roughly *1.x effective votes*, not N (the nine-judges-two-votes
  lesson, applied at persona scale). Any panel description in any
  HydraFlow-format repo MUST state effective-vote honesty wherever seat
  counts appear — "three seats (same substrate: ~1.x effective votes)" —
  and never claim N-seats-as-N-votes. Genuine independence requires
  substrate/context diversity, and even then it is measured (calibration),
  never assumed.

## Relationship to existing judge/eval machinery

The factory already measures its judges: proper-scoring calibration against
escape-ledger ground truth (ADR-0127), finder noise floors (ADR-0126), gate
sensitivity (ADR-0125). Chambers plug into this, not around it: seat verdicts
are judge verdicts (ledger rows), persona survival rates are finder-precision
series, and a chamber's charter is subject to the same drift checks as any
ADR. Where the two conflict, the measured machinery wins — a chamber's
opinion about its own calibration is exactly the self-certification the
three-frame stack forbids.

## Graduation trajectory (from the harvestd reference)

Documented in the reference repo and preserved here as the growth path:
personas graduate into **GitHub-driven feeder loops** (proposal-only, the
ports-and-loops standard), and the console graduates into a **rendered
surface** — a faceplate per persona-loop over the common evidence shape every
run emits. The files remain the contract; the loops become the enactment.

## Stamping the skeleton

`make stamp DIR=<repo> PKG=<pkg> AGENTS_CONSOLE=1` adds the optional layer:

```
agents/
  README.md                 # this pattern, condensed; points here
  personas/README.md        # the persona-contract format (Layer 1)
  console/README.md         # the general chamber contract (Layer 2)
  console/decisions/README.md  # record discipline (Layer 3) — listing is the index
```

Skeleton READMEs are template-owned (re-stampable with `FORCE=1`); the
personas and decision records a project accrues are product-owned and never
clobbered.
