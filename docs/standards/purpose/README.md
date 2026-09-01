# HydraFlow Standard — Purpose

A repository states what it is for, and the goals it states are cited by
something that claims to serve them. That is the whole standard. It does not
ask whether the work *achieves* those goals, and it cannot.

Purpose is the first layer of the PAAA model (ADR-0143) and was, for a year,
the one layer nothing checked. Ruling 3 left it that way deliberately and set a
condition: no check may be added "without a ruling that says what checking
intent would even mean." The operator made that ruling on 2026-08-31, recorded
as ADR-0143's 2026-09-01 amendment, and this document is the standard it
licenses.

## What is checkable, and what is refused

Three readings were on the table. Two are adopted and one is refused
permanently, and the split is between **structural** claims and **semantic**
ones:

| reading | verdict | where it lives |
|---|---|---|
| Intent is **stated** — a non-empty `purpose.product` and at least one goal | adopted | `missing-purpose` in `compute_charter_drift` |
| Each goal is **cited** by some Article or standard | adopted | `purpose` standard, through the policy seam |
| The work **serves** the purpose | **refused** | — |

The third is not deferred, it is refused. No deterministic check can decide it,
and a judge-model check would rest a conformance claim on an external service
being reachable, which #11687 forbids. It is written here so nobody
re-proposes it.

## Why "stated" is fatal and "cited" is not

`missing-purpose` is fatal for a reason that is sequence, not severity. Goal
referential integrity resolves goal ids against the Articles, so a charter with
no goals hands that check an empty subject list — and a check with an empty
subject list passes silently and *reads as coverage*. That is the
`uncheckable-charter` failure one layer up. Tolerating an unstated purpose
would let the stronger check quietly disable itself.

An **unanchored goal never blocks a merge**. It is governance hygiene for a
human: cite the goal where it is genuinely served, or drop a goal the repo does
not pursue. Gating a merge on it would make every PR answerable for the
charter's editorial state, which is neither the author's business nor decidable
at merge time.

## What counts as a citation

A goal id appearing, as a whole word, in any of:

- a standard's `README.md` under `docs/standards/`
- an ADR under `docs/adr/`
- a `local` article statement in the charter

`charter.yaml`'s own `purpose.goals` block does **not** count. Declaring a goal
is what creates the obligation; letting the declaration satisfy it would anchor
every goal by construction and make the check vacuous.

Matching is whole-word, so `lights_off` is not anchored by
`lights_off_operation`. A substring match would let any goal be satisfied by a
longer sibling that happens to contain it.

## How a standard cites a goal

A `## Goals served` section naming the goal ids, as this repo's eight standards
now carry. Cited by id so the link is greppable rather than implied — the point
of the check is that an uncited goal is decoration, and prose that gestures at a
goal without naming it is exactly what "decoration" means here.

## Enforced by

The gates that hold this document to its artifact. This list is the same set as
`enforced_by` in [`standard.yaml`](standard.yaml); editing either side alone
reddens `tests/architecture/test_standards_registry.py`, which also checks that
every cited path is still **collected by pytest** — a gate that exists but never
runs is a citation to nothing.

<!-- standard:enforced-by -->
- `tests/test_charter_purpose_presence.py`
- `tests/test_policy_purpose_standard.py`
<!-- /standard:enforced-by -->

## Goals served

Charter purpose goals this standard carries (ADR-0143 Amendment 2026-09-01,
#11856). Cited by id so the link is greppable rather than implied — an uncited
goal is decoration, and `STANDARD_PURPOSE` says so.

- `every_claim_backed_by_a_check`

A goal nothing claims to serve is a claim with no check behind it. This standard
is that rule applied to the charter's own top layer.
