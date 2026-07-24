# Sampled adversarial re-audit: the silent-escape estimator

**Status:** proposal (2026-07-23). **Companion to:** #10367 (escape ledger). The ledger counts *detected* escapes; "you don't know what you don't know" remains the strongest standing objection to gate-mediated quality. This instrument bounds the *undetected* rate with statistics instead of assertion — acceptance sampling applied to the gauntlet itself.

## The gap

Every merged change passed the gauntlet once, judged by contexts and models adjacent to the ones that wrote it. Nothing ever re-examines a merged change with fresh, adversarial eyes. Consequences: the undetected escape rate is unmeasurable, gate drift is invisible until an escape surfaces in production, and the strongest steelman charge (silent rot under green dashboards) has no standing counter-evidence — only retrospectives.

## Design

### Sampling policy (decided)

- Random sample of merged PRs, default **5%**, stratified: elevated rate for high-blast-radius classes (structural/ADR-touching, security-adjacent paths, migrations, changes touching the gauntlet or merge policy itself)
- **Rate is governed, not fixed**: widen toward a 20% ceiling while disagreement runs above its control limit; narrow toward a 2% floor when quiet. Shewhart's rule applied to the gauntlet — sampling effort follows observed variation
- Token budget per tick caps total audit spend; sampling is the point, exhaustive re-review is an explicit non-goal

### Audit shape (decided)

- Fresh context, no artifacts from the original run beyond the merged diff, the spec/issue, and the repo state — the auditor must not see the original verdicts before forming its own
- Adversarial charter: "find the reasons this merged change is wrong, unsafe, or unfaithful to its spec" — a refuter, not a rubber stamp
- Different model family from the implementing agent when the configured roster allows (see the judge-independence proposal); at minimum a fresh same-family context
- Output: `agree` | `disagree` verdict + findings, recorded to `<data_root>/diagnostics/audit_samples.jsonl`

### Disposition (decided)

Disagreements file `hydraflow-find` issues and take the standard adjudication path: fix, refute with evidence, or encode the exception. Both outcomes feed calibration:

- **Upheld disagreement** → a silent escape found; cross-linked into the escape ledger (`detection_source: sampled-audit`) and counted against the gate class it implicates
- **Refuted disagreement** → the auditor's false-alarm rate; an auditor that over-fires gets its own alarm budget tightened (an instrument that cries wolf gets rationally dismissed)

### Metrics and surfaces

- **Disagreement rate with confidence interval** — the headline: a statistical bound on the undetected escape rate
- **Auditor false-alarm rate** — keeps the instrument honest in the other direction
- **Per-gate-class calibration signal** — which gate the upheld disagreements implicate, feeding `DetectorCalibrationLoop`'s territory
- Regenerated `docs/arch/generated/gauntlet-calibration.md` + dashboard panel

### Loop shape

`SampledAuditLoop`: ADR-0029 caretaker, Pattern B — samples, audits, records, files findings; never reverts, never blocks, never opens fix PRs. Cursor conventions per `ErosionMetricsLoop`.

## Non-goals

Not a merge gate (strictly post-merge), no auto-revert, no exhaustive coverage, no re-audit of the audit (the false-alarm metric is the check).

## Acceptance criteria

- Sampling selects merged PRs at the configured base rate with stratification; the governed rate demonstrably widens/narrows against synthetic disagreement series within its floor/ceiling
- Auditor runs receive no original-verdict contamination (verifiable from the audit record's input manifest)
- An upheld disagreement produces exactly one `hydraflow-find` issue and one escape-ledger cross-link; a refuted one increments the false-alarm series
- Disagreement rate renders with a confidence interval in the generated report and dashboard
- Per-tick token budget is enforced under a synthetic backlog

## Open questions (for planning)

- Stratification weights per blast-radius class — planning picks v1 numbers
- Should audit findings that are stylistic-only (no correctness/safety content) be excluded from the disagreement metric to keep it aligned with the escape definition?
- One-time retrospective sampling over the pre-instrument history (pairs with the escape-ledger backfill question)?
