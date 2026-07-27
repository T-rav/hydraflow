# ADR-0113: ADR lineage — Precedent and Divergence lines

**Status:** Accepted
**Date:** 2026-07-26
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_audit_lineage_check.py::test_control_plane_adr_missing_both_lines_fails

**Precedent:** Software traceability — the requirements-to-rationale linkage tradition (Gotel & Finkelstein, "An Analysis of the Requirements Traceability Problem", 1994; Cleland-Huang et al., *Software and Systems Traceability*, Springer 2012)
**Divergence:** the traceability tradition links artifacts curated by people who reread the rationale before they act; here the corpus is read at *execution time* by generative agents that invent silently, so an unforced invention is indistinguishable from an inherited one — the forcing condition #10674 names — and the rule is that a control-plane ADR names its inherited tradition (Precedent) or its forced break with one (Divergence, citing a receipt), making unforced invention a visible defect (receipt: #10674, docs/proposals/lineage-pass-precedent-divergence.md)

## Context

The factory's design principles read as invented in places where they are in
fact inherited. The vitals monitor names its ancestry — Shewhart individuals
charts, residual monitoring under analytical redundancy — and is more
trustworthy for it: a reviewer who sees a named tradition inherits decades of
failure analysis for free. Most control-plane ADRs do not make that move.
Nothing in the corpus separates the decisions that stand on established
engineering from the decisions that genuinely diverge from it, so both read
alike, and the genuinely novel parts are illegible because nothing marks where
the map runs out.

The working heuristic from the landed proposal
(`docs/proposals/lineage-pass-precedent-divergence.md`, #10673): **unforced
invention is a defect; forced invention has a named forcing condition and a
receipt.** The corpus should make that distinction machine-visible.

This is a change to the ADR *format*, and the ADR format is a contract owned by
[ADR-0044](0044-hydraflow-principles.md) (the audit contract and its
check-table convention). Extending that contract with new parseable fields, and
adding an audit check that reads them, is exactly the kind of change ADR-0044
says must be recorded as its own ADR rather than slipped in as a doc tweak —
hence this record. It amends, and does not supersede, ADR-0044.

## Decision

Extend the ADR format with two **optional**, single-line fields, parseable in
the same header-field style ADR-0044 already uses (`**Status:**`,
`**Enforcement:**`):

- **`Precedent:`** — the named engineering tradition this decision inherits,
  with its canonical source. Format: `Precedent: <tradition> (<canonical
  source>)`. It must name a **real, citable** tradition; retrofitted branding
  (a grand-sounding label with no literature behind it) fails review.
- **`Divergence:`** — the assumption in that tradition that breaks here, stated
  as *assumption, forcing condition, rule*, **citing the receipt** — an ADR, an
  incident, or an audit finding — that forced the break. Format: `Divergence:
  <assumption>, <forcing condition>, <rule> (<receipt>)`. **A `Divergence:`
  without a receipt is not accepted**: a divergence with no forcing evidence is
  indistinguishable from unforced invention, which is the defect this pass
  exists to surface.

Rules:

1. A **control-plane ADR** — a decision that defines the control system —
   carries at least one of the two lines. The audit fails on absence
   (STRUCTURAL since the seed pass landed, #10674; it began advisory).
2. The format is parseable, so the audit can extract a lineage table from the
   corpus (inherited vs novel, straight off the fields).
3. Neither field is required on non-control-plane ADRs. The pass is about the
   decisions that define the control system, not every record.
4. Both forms — bold-inline (`**Precedent:** ...`) and plain (`Precedent:
   ...`) — parse identically; write the field as its own line, not a bullet.

The control-plane set this pass targets (from the proposal, refined as the seed
pass lands): ADR-0002, 0029, 0044, 0049, 0051, 0094–0101, 0103, 0104, plus the
vitals and judge-independence records once they have standalone ADRs.

### Enforcement — advisory first, now STRUCTURAL

The audit gains a check under ADR-0044's P1 table (`P1.17`, implemented in
`scripts/hydraflow_audit/checks/p1_docs.py`, backed by the pure parser in
`scripts/hydraflow_audit/lineage.py`). It **FAILs** the gate when a control-plane
ADR present in the corpus carries neither line, and flags any `Divergence:` line
that cites no receipt token. It **started CULTURAL and advisory** — reported but
never failing the audit gate — while the seed pass that backfills the corpus
(#10674 child 3) was in flight; failing the gate before the lines existed would
only have punished compliant work. Now that every control-plane ADR carries a
verified line, the check has **escalated to STRUCTURAL** (fail on absence) and
been removed from `scripts.hydraflow_audit.runner.ADVISORY_CHECKS` (#10674 child
5). This mirrors the ratchet-and-grandfather discipline the rest of the audit
uses: advisory until the floor is met, blocking after.

The check is deterministic and side-effect-free (it reads `docs/adr/*.md` and
parses text), so it satisfies ADR-0044's requirement that an `enforced` check
resolve to a real, non-mutating artifact.

## Consequences

**Positive**
- A reviewer previously unfamiliar with the repo can, from ADR text alone, tell
  inherited from novel — and inherit the failure analysis that comes with a
  named tradition.
- The distinction between forced and unforced invention becomes
  machine-visible: `Divergence:` without a receipt is a concrete, greppable
  defect, not a matter of taste.
- The audit can extract a lineage table from the corpus for docs and review.

**Negative**
- Two more optional fields to maintain on the control-plane set, and a seed
  pass to verify each tradition is real (retrofitted branding is worse than
  silence).
- The control-plane set is a hand-maintained list until the vitals /
  judge-independence records get standalone ADRs.

**Neutral**
- The check is blocking as of the seed pass (#10674): a reader who sees P1.17
  FAIL in `make audit` should read it as "a control-plane ADR is missing its
  lineage line, or a `Divergence:` cites no receipt", not "the corpus is
  mid-backfill". While the seed pass was in flight the check was advisory (WARN,
  non-blocking); that grandfather window is now closed.

## Alternatives considered

**A prose "Lineage" section instead of one-line fields.** Rejected: a free-form
section is not machine-parseable, so the audit could neither warn on absence nor
extract a lineage table. Single-line fields keep the same
extract-and-check machinery ADR-0044 already uses for the check tables.

**Require both fields on every ADR.** Rejected: most ADRs are implementation
records, not control-system decisions; demanding a tradition for each would
manufacture exactly the retrofitted branding this pass forbids.

**Skip the ADR and just add the fields + check.** Rejected: this changes the
ADR-0044 format contract, and ADR-0044 explicitly makes a contract change an
ADR-level decision (the intended friction). `Skip-ADR` is for
implementation-level touchpoints, not contract changes.

## Related

- [ADR-0044](0044-hydraflow-principles.md) — the audit contract and check-table
  convention this ADR extends (P1.17 added to its P1 table)
- [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) — the sibling
  "living artifact" pattern; the wiki term `lineage` (#10674 child 4) makes the
  vocabulary CI-enforced
- [ADR-0099](0099-orchestration-as-a-control-system.md) — seeded as a
  live exemplar (its Precedent/Divergence lines are the control-system mapping)
- `docs/proposals/lineage-pass-precedent-divergence.md` — the landed proposal
  this implements (#10673)
- `scripts/hydraflow_audit/lineage.py`, `scripts/hydraflow_audit/checks/p1_docs.py`
  — the parser and the P1.17 check
