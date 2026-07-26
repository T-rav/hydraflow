# Lineage pass: Precedent and Divergence lines on the control-plane ADRs

**Status:** proposal (2026-07-26). **Depends on:** ADR-0044 (the audit contract and its check-table convention); touches the ADR template and `scripts/hydraflow_audit/`.

## The gap

The factory's design principles read as invented in places where they are inherited. The vitals monitor names its ancestry (Shewhart individuals charts, residual monitoring under analytical redundancy) and is more trustworthy for it: a reviewer who sees a named tradition inherits decades of failure analysis for free. Most control-plane ADRs do not make that move. Nothing in the corpus separates the decisions that stand on established engineering from the decisions that genuinely diverge from it, so both read alike — and the genuinely novel parts are illegible because nothing marks where the map runs out.

The working heuristic: unforced invention is a defect; forced invention has a named forcing condition and a receipt. The corpus should make that distinction machine-visible.

## Design

Extend the ADR format with two optional single-line fields, parseable per the ADR-0044 convention:

- **`Precedent:`** the named tradition this decision inherits, with its canonical source. Must be a real, citable tradition; retrofitted branding fails review.
- **`Divergence:`** the assumption in that tradition that breaks here, stated as *assumption, forcing condition, rule*, citing the receipt (ADR, incident, or audit finding) that forced it. A `Divergence:` without a receipt is not accepted.

Rules:

1. A control-plane ADR (list below) carries at least one of the two lines. The audit warns on absence (CULTURAL check to start; escalate to STRUCTURAL once the seed pass lands).
2. Format is parseable — `Precedent: <tradition> (<source>)` — so the audit can extract a lineage table from the corpus.
3. Neither field is required on non-control-plane ADRs; the pass is about the decisions that define the control system, not every record.

## Seed pass (first mappings, to be verified during implementation)

| Decision / mechanism | Precedent | Divergence |
|---|---|---|
| ADR-0099 orchestration as control system | Feedback Control of Computing Systems (Hellerstein et al. 2004); MAPE-K (Kephart & Chess 2003); the Watt governor | Plant is software production, not a running system; actuators are generative models |
| Shewhart limits (sampled audit, second-order vitals) | Statistical process control (Shewhart 1931; Wheeler) | — |
| Judge independence (out-of-family verdicts) | Two-person rule / separation of duties; N-version programming (Avizienis) | Redundant "versions" are model families sharing training-data ancestry; independence is partial by construction |
| Self-modification fail-closed class | Configuration control on safety-critical software (DO-178C tradition) | The plant can edit the controller: graded work and grading machinery share one repository |
| Model-version markers / trust resets | Metrology: recalibration after instrument replacement | Classical control never has its actuator swapped mid-run for a differently-behaved one |
| Pattern B read-only instruments (ADR-0029) | Measurement/actuation separation; Goodhart's law | Instrument and actor share a repository and write capabilities unless separated by rule |
| Finding-rate budgets on instruments | SRE error budgets (Google SRE, 2016) | — |
| Disturbance dampener / baselines (ADR-0101) | Ratchet/baseline practice in lint tooling; SPC baselining | Baseline is committed and adversarially auditable because the machine, not a person, burns it down |
| Fail-closed defaults (ADR-0049 kill switches, gates) | Safety engineering default-deny; fail-safe design | — |
| Ubiquitous language enforced in CI | Domain-Driven Design (Evans 2003) | The consumer of the vocabulary is a machine acting at execution time, not a team talking |
| MockWorld scenarios | Simulator training tradition (aviation type-rating) | The simulator gates merges, not just training |
| Labels-as-state (ADR-0002) | Stigmergic coordination; blackboard architectures | — |
| Auto-tighten ratchet (ADR-0104) | Ratchet testing practice | Floor raises are machine-proposed from attributed evidence, monotone-guarded |
| Green-while-dying vitals | Residual monitoring / analytical redundancy (FDI literature) | The redundant estimates audit the verification system, not the plant |

## Deliverables

1. ADR template gains the two optional fields, one-line format documented.
2. Seed pass lands `Precedent:`/`Divergence:` on the control-plane list: ADR-0002, 0029, 0044, 0049, 0051, 0094–0099, 0100, 0101, 0103, 0104, plus the vitals and judge-independence records.
3. `hydraflow_audit` gains the CULTURAL check (warn on a control-plane ADR without either line), per the ADR-0044 check-table convention.
4. Wiki term `lineage` so the vocabulary is enforceable.

## Acceptance

- Every control-plane ADR carries a verified line; no `Divergence:` without a named receipt.
- The audit can extract the lineage table from the corpus.
- A reviewer previously unfamiliar with the repo can, from ADR text alone, tell inherited from novel.
