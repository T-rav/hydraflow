# ADR-0136: ADR drift enforcement is a deterministic cited-symbol CI gate, not a caretaker loop

- **Status:** Accepted
- **Date:** 2026-08-22
- **Enforcement:** enforced
- **Binds:** both
- **Supersedes:** [ADR-0056](0056-adr-touchpoint-gate-to-caretaker-loop.md) (ADR touchpoint enforcement — synchronous gate → asynchronous caretaker loop)
- **Superseded by:** none
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (the caretaker pattern this decision removes two members from), [ADR-0100](0100-adr-conformance-as-a-measured-contract.md) (the sibling conformance contract, which keeps its own loop), [ADR-0082](0082-declarative-gate-contract.md) (the branch-protection contract whose "ADR enforcement lives in a loop" boundary claim this ADR corrects), [ADR-0065](0065-remove-code-grooming-loop.md) (precedent: a caretaker loop removed by ADR when its value did not justify its machinery). Code: `src/adr_citation_resolve.py:unresolved_citations`, `src/adr_index.py:ADRIndex`, `src/adr_drift.py:bare_infra_citation_nudges`. Issues: #10540 (the retirement decision), #10533 (the guard it generalized), #11600 (the flag-rot audit that forced this ADR).

**Enforced by:**
pytest:tests/test_adr_citation_conformance.py::test_no_unresolved_adr_citations
pytest:tests/architecture/test_adr0136_adr_drift_loops_removed.py::test_no_live_adr_drift_loop_references

## Context

[ADR-0056](0056-adr-touchpoint-gate-to-caretaker-loop.md) replaced a synchronous "ADR touchpoint" CI gate with `AdrTouchpointAuditorLoop`, an [ADR-0029](0029-caretaker-loop-pattern.md) caretaker that scanned merged PRs and filed a `hydraflow-adr-drift` rollup issue whenever a PR touched a `src/` module some Accepted ADR cited. A sibling loop, `AdrDriftResolverLoop` (#9976), existed only to spend LLM calls triaging those rollups so the ones that were wrong could be auto-closed.

The signal the auditor produced is **activity**, not violation: "work happened in a file an ADR mentions." Measured over ~2 months in production it was ~13% of all filed issues and ~29% of the open backlog, at roughly **70% false positives** (#10540). Four successive amendments tried to raise its precision — symbol-aware citations (#9176), a hand-maintained shared-infra allowlist (#9397), a churn-derived fan-out suppression (#10456), fleet batching (#9662) — and a whole second loop was built to LLM-triage what remained (#10457). The precision problem is structural, not tunable: a file-diff intersection cannot distinguish "this decision changed" from "someone edited a file this decision mentions."

**#10540 (closed 2026-07-25, PR #10547) decided the replacement** and shipped it: `src/adr_citation_resolve.py` AST-resolves every symbol-qualified `src/<module>.py:<Symbol>` citation in a live ADR against the on-disk module (no import), and `tests/test_adr_citation_conformance.py::test_no_unresolved_adr_citations` fails the normal "Tests" CI lane naming the exact `ADR-NNNN path:Symbol` list. A citation that no longer resolves is a **concrete violation**, and the PR that renamed the symbol fixes the citation in that same PR — self-healing at the source instead of a post-merge issue queue.

#10540 flipped both loops' kill-switches to default-`False` and explicitly deferred deletion ("Loops stay in tree, disabled; a later PR can delete them"). That later PR never came. The 2026-08-21 flag-rot audit (PR #11599) rostered them in **#11600** and could not remove them, because deleting the loops would contradict ADR-0056 — still `Accepted`, still un-superseded, and still symbol-citing the very files to be deleted, so the deletion would have broken this ADR's own citation gate for a live ADR. Removing the machinery requires a superseding ADR first. This is that ADR.

## Decision

**ADR-to-code drift is enforced by a deterministic, violation-based CI gate. The activity-based caretaker loops are retired and deleted.**

1. **The gate is the enforcement boundary.** `adr_citation_resolve.unresolved_citations` resolves every symbol-qualified citation of every **live** (Accepted / Proposed) ADR against the source tree via `ast.parse`. `test_no_unresolved_adr_citations` runs in the normal Tests lane on every PR. A cited path that is missing, or a `:Symbol` tail that no longer resolves, fails CI naming the citation to fix.

2. **`AdrTouchpointAuditorLoop` and `AdrDriftResolverLoop` are deleted**, with their flags (`adr_touchpoint_auditor_loop_enabled`, `adr_drift_resolver_loop_enabled`), their satellite config (intervals, `adr_drift_fleet_batch_threshold`, `adr_drift_resolver_tool` / `_model` / `_timeout` / `_provider` / `_max_triage_per_tick`), their labels (`adr_drift_label`, `adr_drift_stuck_label`), their `adr_audit_*` / `adr_rollup_issues` state, and the full loop wiring (orchestrator registry, `ServiceRegistry`, scenario catalog, sandbox scenario, dashboard interval bounds and control rows, UI worker catalog, fleet manifest).

3. **What survives, and why.** Three pieces of the retired machinery outlived the loops and stay:
   - `adr_drift.bare_infra_citation_nudges` (+ `_is_shared_infra`, `CitationNudge`, `_SHARED_INFRA_MODULES`) — a non-blocking **authoring nudge** rendered into `docs/arch/generated/adr_xref.md` by `src/arch/generators/adr_cross_reference.py`. It suggests re-citing a bare shared-infra citation at `:Symbol` granularity, which is exactly what makes a citation *enforceable* by rule 1. It never was a drift signal and is not one now. The churn-derived fan-out branch that used to OR into `_is_shared_infra` (#10456, `adr_drift_shared_infra_fanout_threshold`) goes with the loops: its only supplier was `compute_drift`, and the offline generator deliberately passes no config, so the branch was already inert in production and the generated artifact is unchanged.
   - `src/state/_adr_audit.py`, which also carries [ADR-0100](0100-adr-conformance-as-a-measured-contract.md)'s `adr_conformance_*` namespace. Only the `adr_audit_*` / `adr_rollup_*` half is removed.
   - `src/adr_citation_resolve.py` and `tests/test_adr_citation_conformance.py` — the replacement, untouched.

   The `adr_drift` entry in the [ADR-0126](0126-golden-baseline-finder-calibration.md) finder catalog goes **with** the loops, not against them. That catalog measures the *noise floor of a generative (LLM) finder* — `src/finder_faceplate.py:FINDER_LOOP_WORKER` maps each finder id to exactly one loop whose filed-findings count is its live rate. `adr_drift` stood for `AdrTouchpointAuditorLoop`, and its clean-tree detector only ever used `adr_citation_resolve` as a deterministic *stand-in* for the loop's PR-diff signal. With no loop there is no generative output to calibrate, and the stand-in's floor is trivially zero because the gate in rule 1 already fails CI on every PR — so a faceplate row for it would report a CI invariant as if it were LLM noise. The row, its `DETERMINISTIC_DETECTORS` entry, and its `control/fleet.yaml` join are removed; the gate itself is unaffected.

4. **`AdrConformanceLoop` (ADR-0100) is untouched.** It answers a different question — does each Accepted ADR's `**Enforced by:**` check resolve and really assert — and its signal is a measured contract, not an activity heuristic. This ADR retires activity-based *drift*, not ADR governance loops as a category.

### Rules

1. **Enforceability is a property of the citation.** Only a symbol-qualified `src/<module>.py:<Symbol>` citation is enforced. A bare `src/<module>.py` citation is a *dependency pointer* — deliberately exempt (`src/adr_citation_resolve.py:_unresolved_for_adr`), because a removal ADR legitimately cites the file it removed and a Proposed ADR forward-references a file that does not exist yet. An ADR that wants a decision anchor held to the tree must name the symbol.
2. **Live ADRs only.** Superseded and Deprecated ADRs are frozen history; their citations may point at deleted code and are never gate failures. This is what makes retiring an ADR — including ADR-0056 — a legal way to release its citations.
3. **The fix belongs in the PR that broke it.** Drift is not queued work. A PR that renames or deletes a cited symbol repoints the citation in that PR, or the merge does not go green. There is no rollup issue, no dedup key, no attempt counter, and no `Skip-ADR:` escape hatch (ADR-0056's Rule 4 survives its own ADR).
4. **No LLM in the drift path.** The gate is pure AST resolution — no `gh` calls, no credits, no triage. A deterministic answer needs no second loop to decide whether to believe it.

## Consequences

**Positive:**
- The dominant source of factory backlog noise is gone: ~29% of the open board at ~70% FP no longer has a producer.
- Drift is caught **before** merge instead of up to one 4h interval after it, and it is caught by the PR that caused it, which is the PR that can cheapest fix it.
- ~2,600 lines of loop, triage, runtime, and pure-engine code and their wiring leave the tree, along with two credit-spending code paths (`adr_drift_resolver_tool`/`_model`).
- The enforcement claim in [ADR-0082](0082-declarative-gate-contract.md) becomes true again. It said "ADR enforcement stays with the `adr_touchpoint_auditor` loop"; the loop had been dark since #10540, so the branch-protection standard was asserting a boundary that did not exist — the exact "do not lie about enforcement boundaries" failure ADR-0082 itself was written about.

**Negative:**
- **Coverage narrows on purpose.** The auditor flagged *any* change to a cited file; the gate only fails when a cited symbol stops resolving. A PR that changes what a cited symbol *does* without renaming it drifts the ADR's prose and no longer trips anything automatically. This is the accepted trade: #10540 judged 70% false positives a worse failure than a known false-negative class, and the residual is covered by human review plus ADR-0100's conformance measurement.
- Bare-cited ADRs get no enforcement at all. Mitigation: `bare_infra_citation_nudges` surfaces every one of them in the generated cross-reference as an authoring nudge.
- One fewer caretaker loop pair in the fleet changes loop-count-derived baselines (`disturbance/baselines/mass.yaml`, `suppressions.yaml`), which shrink accordingly.

**Migration:**
- Persisted `adr_audit_cursor`, `adr_audit_attempts`, and `adr_rollup_issues` keys in existing `state.json` files are silently dropped: `StateData` is `ConfigDict(extra="ignore")`, so no state migration is required and no operator action is needed.
- Dedup stores at `dedup/adr_touchpoint_auditor.json` and `dedup/adr_drift_resolver.json` become orphaned files on disk. They are inert (nothing reads them) and cost a few KB; no cleanup is required.
- The `hydraflow-adr-drift` and `hydraflow-adr-drift-stuck` labels stop being created by `src/prep.py`. Both had **zero open issues** at the time of removal, so no live work is orphaned. Existing closed issues keep their labels in GitHub's history.
- Runtime `config.json` files carrying the removed keys are harmless: `load_runtime_config` / `apply_repo_config_overlay` filter unknown keys.

## Alternatives considered

- **Keep the loops dark in-tree.** Rejected: this is the status quo #11600 filed against. A default-OFF flag guarding retired machinery is rot that costs review attention, test runtime, arch-generation surface, and mass/suppression budget on every PR forever — and it leaves an Accepted ADR asserting a live enforcement boundary that has been dark for a month.
- **Re-enable the auditor with a higher precision threshold.** Rejected by #10540 after four precision amendments and a second LLM loop failed to move it off ~70% FP. The signal is activity; no threshold turns activity into violation.
- **Make the citation gate a caretaker loop instead of a CI test.** Rejected: the gate is deterministic, pure, and sub-second, so a loop would add a scheduling interval, dedup state, and an issue queue for an answer CI can give synchronously — the exact inversion ADR-0056 made, for a signal that (unlike activity) actually justifies blocking.
- **Delete `src/adr_drift.py` entirely.** Rejected: `bare_infra_citation_nudges` has a live non-loop consumer (`src/arch/generators/adr_cross_reference.py`) and directly serves rule 1 by nudging bare citations toward enforceable symbol granularity. Only the loop-only half of the module is removed.
