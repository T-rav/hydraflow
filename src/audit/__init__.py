"""Sampled adversarial re-audit — the silent-escape estimator (#10370).

Companion to the escape ledger (#10367): the ledger counts *detected* escapes;
this instrument bounds the *undetected* rate with statistics instead of
assertion. Acceptance sampling applied to the gauntlet itself — a governed
random sample of merged PRs is re-reviewed by a fresh, adversarial context and
the disagreement rate becomes a statistical bound on silent escapes plus a
standing calibration signal for the gates.

Layered like the sibling ``escape`` package (mirror-the-style, don't
cross-import for shared logic — the ONE deliberate cross-link is the upheld-
disagreement path, which REUSES ``escape.ledger``/``escape.models`` rather than
forking the ledger writer):

* ``models`` — value objects (``MergedChange`` sampling input, ``AuditSample``
  ledger row, verdict / disposition literals, governance observations).
* ``stratify`` — pure blast-radius classification + per-class stratum weight.
* ``sampling`` — pure stratified random selection at a governed rate.
* ``governance`` — the Shewhart rate governor: widen toward the ceiling while
  disagreement runs above its control limit, narrow toward the floor when quiet.
* ``budget`` — pure per-tick token-budget cap on audit spend (sampling is the
  point; exhaustive re-review is an explicit non-goal).
* ``store`` — the append-only ``audit_samples.jsonl`` reader/writer.
* ``metrics`` — disagreement rate + Wilson confidence interval (the headline
  statistical bound), auditor false-alarm rate, per-gate-class calibration.
* ``disposition`` — pure adjudication reconcile: an upheld disagreement crosses
  into the escape ledger, a refuted one increments the false-alarm series.
* ``crosslink`` — build an ``escape.models.EscapeRecord`` for an upheld
  disagreement (``detection_source: sampled-audit``), reusing the escape
  ledger writer/schema.

Metrics surface on the shared gauntlet-calibration dashboard panel
(``/api/diagnostics/gauntlet-calibration``, which reads ``audit_samples.jsonl``);
the committed ``docs/arch/generated/gauntlet-calibration.md`` is a deterministic
instrument spec rendered by ``arch.generators.gauntlet_calibration`` (shared with
#10371). The loop writes no git-committed artifact at runtime.

The consuming caretaker is ``sampled_audit_loop.SampledAuditLoop`` — a
read-only ADR-0029 Pattern-B sensor: it samples, audits, records, files
findings; it NEVER reverts, blocks, or opens fix PRs, and it is strictly
post-merge (the escape already merged; the re-audit is measurement, not a gate).
"""
