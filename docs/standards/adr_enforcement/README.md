# HydraFlow Standard — ADR Enforcement

Every Accepted ADR records a decision. A decision nobody can *check* is a
decision that silently rots: the code drifts, nothing turns red, and the ADR
becomes a lie on disk. This standard makes REAL enforcement the default and the
debt visible and shrinking — the same ratchet discipline HydraFlow already
applies to test duration, suppressions, and disturbance dimensions.

The source of truth already exists. `classify_adr_enforcement`
(`src/adr_conformance.py`, rendered to
`docs/arch/generated/adr-enforcement.md`) classifies every Accepted ADR as:

- **REAL** — the ADR is `enforced` and cites at least one resolving,
  non-mutating, *asserting* check (a `pytest:` node/module that actually
  asserts, or a `make:` guard target).
- **WEAK** — there is an `**Enforced by:**` pointer, but it is not a real
  machine check: a `manual` prose pointer, or an `enforced` ADR whose checks
  don't resolve / are mutating.
- **MISSING** — no `**Enforced by:**` check at all (typically a bare
  `decision-of-record`).

`WEAK` + `MISSING` are the **unenforced-decision debt**. This standard turns the
honest-but-toothless report into a merge gate.

## The rule

> **Every `enforced` Accepted ADR must classify `REAL`. A `manual` or
> `decision-of-record` kind is allowed only via an explicit, justified
> allow-list entry. The unenforced-decision debt is monotonically
> non-increasing — it may only shrink.**

Concretely, for any Accepted ADR:

1. **Prefer a REAL check.** Set `**Enforcement:** enforced` and cite a
   resolving, non-mutating, asserting `**Enforced by:** pytest:tests/...::Test...`
   (or `make:<guard-target>`). This is the default and the only path that adds
   no debt.
2. **If — and only if — no machine-checkable invariant is feasible**, the ADR
   may be `manual` / `decision-of-record`, but the id must be added to the
   justified allow-list in [`exemptions.md`](exemptions.md). Honest exemption is
   cheap; dishonest silence is expensive.
3. **A NEW Accepted ADR may never grow the debt.** It ships REAL enforcement or
   a justified exemption — it does not get added to the baseline.

## Two lanes: baseline vs exemptions

The debt is drained through two distinct, non-overlapping lanes. Confusing them
is the most common mistake.

| Lane | File | Meaning | Grows? |
|---|---|---|---|
| **Baseline** (grandfathered debt) | `tests/architecture/adr_enforcement_baseline.json` | The frozen snapshot of debt that existed when the ratchet landed. It **must burn down** — each ADR here is a to-do, not a permanent state. | Never. Only shrinks (via `resolved`). |
| **Exemptions** (allow-list) | [`exemptions.md`](exemptions.md) | ADRs that legitimately *cannot* have a resolving check — genuinely process-only decisions. A permanent, justified statement, not deferred work. | Yes, one justified entry at a time. |

The baseline is the honest debt ledger; the exemption list is the honest
"unenforceable by nature" ledger. An ADR belongs to at most one of them.

## How to pay a debt down

Each of the 12 grandfathered ADRs is resolved in exactly one of two ways, and
the ratchet directs you to the right one when its state changes:

- **Gave it a REAL check** → move its id from the live grandfathered set into
  the `resolved` list in `adr_enforcement_baseline.json`. (Do **not** edit the
  frozen `baseline_snapshot` literal — that is the fixed high-water mark. Adding
  to `resolved` is how the live set shrinks, mirroring the
  `_GRANDFATHERED = _BASELINE - _RESOLVED` idiom in
  `tests/test_adr_conformance_coverage.py`.)
- **Concluded it is genuinely process-only** → add a justified entry to
  [`exemptions.md`](exemptions.md).

## When an exemption is legitimate

Some decisions are process-only and have no on-disk invariant a test could
assert — e.g. an iterative-review cadence, or a human-judgment escalation
policy. For those, the *good* enforcement is a justified exemption, not a fake
test that asserts nothing (a hollow check that stays green while the decision
drifts is worse than an honest exemption).

An exemption is legitimate when **all** of these hold:

- No `pytest:` invariant and no `make:` guard could fail when the decision is
  violated — the decision is about human process, cadence, or judgment.
- The one-line justification names *why* no check is feasible, not just *that*
  the ADR is manual.
- The ADR does not already classify `REAL` (if it does, it needs no exemption).

If you can imagine a test that would turn red on violation, it is debt, not an
exemption — write the check.

## Enforcement (this standard is itself enforced)

`tests/architecture/test_adr_enforcement_ratchet.py` rides `make quality` and
imports `classify_adr_enforcement` directly (it never shells out). It fails when:

- a non-exempt Accepted ADR classifies `WEAK`/`MISSING` and is not in the
  baseline (new or un-grandfathered debt);
- the live debt count rises above the baseline snapshot count;
- the frozen `baseline_snapshot` literal is edited (it is a fixed landing
  snapshot);
- a grandfathered ADR now classifies `REAL` but has not been moved into
  `resolved` (the ratchet tightens as debt is paid);
- an id claimed in `resolved` does not actually classify `REAL` now;
- an exemption entry is malformed, names a non-Accepted or already-`REAL` ADR,
  or collides with the baseline / `resolved`.

The live tally is always visible in `docs/arch/generated/adr-enforcement.md`.

## Discoverability

This standard lives at these load-bearing surfaces:

- This document — the canonical reference.
- `tests/architecture/test_adr_enforcement_ratchet.py` — the executable gate.
- `docs/arch/generated/adr-enforcement.md` — the live REAL/WEAK/MISSING tally.
- The `docs/standards/` index in `CLAUDE.md`.

## Relationship to ADR-0100

ADR-0100's coverage ratchet (`tests/test_adr_conformance_coverage.py`) already
requires every Accepted ADR to *declare* an `**Enforcement:**` kind and, for
`enforced` ADRs, that the cited checks *resolve*. This standard pushes the next
rung: it is not enough to declare `manual` and cite prose — the decision must
either bind to a REAL asserting check or earn a justified exemption, and the
debt can only fall. It replaces the earlier debt-only ratchet with a single
standard-linked gate that also reads the exemptions allow-list.
