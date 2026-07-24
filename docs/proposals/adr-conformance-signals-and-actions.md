# ADR conformance as signals-and-actions: enforcement-conformance over citation-drift

**Status:** proposal (2026-07-23). **Supersedes in spirit:** the tactical fix in #10411 (adding two more modules to the `_SHARED_INFRA_MODULES` allowlist). **Direction-sets, does not itself enact:** a follow-up ADR would supersede [ADR-0056](../adr/0056-adr-touchpoint-gate-to-caretaker-loop.md) (citation-touch auditor) and extend [ADR-0100](../adr/0100-adr-conformance-as-a-measured-contract.md) (measured conformance contract). Docs-only; no pipeline code changes here.

## The problem, stated as a signal-quality problem

ADR-drift is the single dominant noise source in the factory's issue lane: **100+ `hydraflow-adr-drift` issues filed to date**, and three recent PRs alone spawned ~15 flags — #10388 (PR #10376 → 4 ADRs), #10406 (PR #10396 → 5), #10405 (PR #10380 → 6) — **every one a false positive** (implementation-only, decision-preserving changes; #10388 closed CONSISTENT per-ADR). The current model (ADR-0056) is a post-merge caretaker that DETECTS "a `src/` module an ADR cites changed without the ADR file in the same diff," files a rollup (or #9662 fleet-batched) issue, hands it to LLM triage, and lets a resolver bot-PR reconcile. It floods the issue/PR lane, senses AFTER the change lands, and makes reconciliation a separate unit of work.

The root cause (#10411) is usually named as a coverage gap — `review_advisor.py` and `review_phase/_phase.py` are the next high-churn shared-infra files not yet on the hand-maintained `_SHARED_INFRA_MODULES` allowlist in `src/adr_drift.py`. But that framing invites another round of whack-a-mole. **The deeper problem is that the signal asserts almost nothing.**

---

## Section 1 — The signal must assert the decision

A drift signal is only worth the assertion it makes. The current sensor's atomic claim is:

> *a file that some ADR cites was edited.*

That claim is nearly independent of the thing we actually care about — **is the ADR's decision still true?** A cited file changes for dozens of reasons that leave the decision untouched: a caller moved, a co-tenant symbol in the same file changed, a type annotation was added, a docstring was reflowed. The prompt in `adr_drift_triage_llm.py` already concedes the point in its own words: *"roughly 70% of these findings are false positives."* A sensor that is ~70% noise is not a weak sensor — it is an **alarm-fatigue generator**. The rational response to a channel that cries wolf two times in three is to stop reading it, which is exactly what 100+ stale open drift issues represent: a signal the humans and the pipeline have both learned to discount.

The math is unforgiving. At a ~70% false-positive rate, the *precision* of a raw citation-touch alert is ~0.3. The machinery built on top of it — symbol-aware suppression (#9176), the `_SHARED_INFRA_MODULES` allowlist, per-ADR rollups (#8987), fleet batching (#9662), LLM triage, the resolver loop — is an increasingly elaborate apparatus for **filtering a bad signal after the fact** rather than emitting a good one. Each addition is real engineering spent recovering precision that a better sensor would never have lost. `_SHARED_INFRA_MODULES` is the tell: a hand-curated list of "files whose changes we've learned to ignore," grown one module at a time across #9397 → `pr_manager` → dashboard/server/repo_runtime → contract_* — and #10411 is the next entry in that ledger. The allowlist is a manually-maintained precision patch on a sensor that measures the wrong quantity.

The valuable event is not *citation touched*. It is **decision ↔ code divergence**: the code now does something the ADR's Decision says it must not, or no longer does something the Decision says it must. That is the event worth a human's attention, and it is the event a citation touch cannot distinguish from routine churn.

**So invert the subsystem.** Stop asking "did a cited file change?" (a proxy that is 70% noise) and start asking "did the decision's own assertion break?" (a signal that is ~0% noise, because it is the decision, mechanized).

---

## Section 2 — Enforcement-conformance as the primary mechanism

The good news: HydraFlow **already built the mechanized-decision signal** and is under-using it. [ADR-0100](../adr/0100-adr-conformance-as-a-measured-contract.md) established that every Accepted ADR (outside a shrinking grandfather list) declares:

- a required `**Enforcement:**` kind — `enforced` | `manual` | `decision-of-record` (an absent/unknown value normalizes to `unknown`, which **fails the coverage ratchet** `tests/test_adr_conformance_coverage.py`, a pre-merge CI-blocking gate); and
- where the kind is `enforced`, an `**Enforced by:**` list of **typed, resolvable checks** (`pytest:tests/...::node`, `make:target`), parsed by `adr_index.parse_enforced_by` into `Check` objects.

Today, across the ADR set: **45 ADRs are `enforced`, 6 are `manual`, 6 are `decision-of-record`** (`src/adr_conformance.py::classify_enforcement`). `adr_reviewer._ensure_enforcement_line` even auto-injects a kind on bot-authored ADRs so nothing flips to Accepted without one. The `Enforced by:` line is not aspirational — `AdrConformanceLoop` (ADR-0100) already **executes** each `enforced` ADR's checks post-merge and files an issue on FAIL/UNRESOLVED, and the ratchet already proves each check *resolves* (AST/file inspection) at PR time.

### The primary signal fires ONLY on enforcement failure

Reframe the whole subsystem around the `enforced` kind:

- An ADR's **primary drift signal is its named enforcement check FAILING** — the `pytest:`/`make:`/arch-invariant guard that encodes its Decision returns FAIL. A concrete example already in the tree: the `src ↛ scripts` boot invariant `tests/architecture/test_src_does_not_import_scripts.py` (the guard behind #10365). If that test goes red, a decision was *genuinely violated* — 0% noise, worth a HITL escalation. A cited file merely changing is not that and never was.
- This signal is **already computed twice**: the enforcement check runs in CI at PR time (inside `make quality` / the gate suite) *and* in `AdrConformanceLoop` post-merge. What is missing is **attribution**: turning a red required check back into "*ADR-00NN's decision was violated by this PR*" so the signal reads as a decision event, not an anonymous test failure. That attribution is the new PR-time surface (the sensor below), not a new detector.

### ADRs whose decision cannot be mechanized get NO per-PR drift signal

An ADR whose kind is `manual` or `decision-of-record`, or an `enforced` ADR whose only checks are `prose`/UNRESOLVED, **cannot** emit a decision-divergence signal — any per-PR alert on it would be pure citation-touch noise by construction. So it gets none. Instead:

- it is honestly carried as `enforcement: manual` / `decision-of-record` (already the case for 12 ADRs today), reviewed periodically by a human, not per-PR by a tripwire; and
- **the count of such ADRs is itself the valuable second-order signal** — the true *unenforced-decision debt*. `~12 of ~57` ADRs carrying an enforcement kind (≈21%) currently assert their decision to no machine. That number, trended, is the honest measure of "how much of our architecture is decided-but-unguarded," and it is *derivable today* from `adr_conformance.evaluate_adrs` output (the `MANUAL`/`SKIPPED` outcomes) with no new detection code. Surfacing and trending it — one standing panel/rollup, not a per-ADR issue storm — turns invisible debt into a governed metric and creates the right pressure: to silence an ADR's noise, give it a real `Enforced by:` check.

### Strengthening weak or absent `Enforced by:` fields

The reframe's leverage depends on the enforcement actually asserting the decision, so the debt metric must also flag **weak** enforcement, not just absent enforcement:

- **absent** — kind is `manual`/`decision-of-record`: counted in the debt metric; a `hydraflow-find` may be filed (rate-budgeted, one rollup) proposing a mechanizable check where one plausibly exists.
- **unresolved** — an `enforced` ADR whose `pytest:`/`make:` target no longer resolves: already handled by ADR-0100's REPOINT/rename path; kept.
- **tautological / weak** — an `enforced` check that resolves and passes but does not actually assert the Decision (e.g. `pytest:` pointing at a test that only imports a module). The ratchet cannot catch this (it checks resolution, not assertion strength). This is a **known residual risk** (see Risks) surfaced for human/`adr_reviewer` judgment, sampled — never auto-trusted as "enforced ⇒ safe."

---

## Section 3 — Residual citation-drift: in-band reconciliation for the unenforceable tail

Citation-drift does not vanish; it is **demoted** from the primary firehose to a weak, advisory, non-lane-flooding backstop that applies **only to the unenforceable tail** — the `manual`/`decision-of-record` ADRs and `enforced` ADRs with prose-only checks, where no enforcement signal can exist. Even there it must not flood. The mechanism is signals-and-actions with in-band reconciliation:

At PR time (shift-left, advisory — the sensor pattern of the RC dry-run #10352: `schedule`/`workflow_dispatch`-shaped, **never a blocking `pull_request` gate**), compute the residual drift set for the PR and classify each touchpoint into exactly one action-class. The classification *is* the signal:

| Class | ~Share | Condition | Action (in-band) |
|---|---|---|---|
| **NOISE** | ~70% | bare high-churn / shared-infra citation, or LLM triage returns `CONSISTENT` | **Self-heal silently.** Write a machine-readable `adr-ack` touchpoint record; feed the churn into the auto-suppression set. No issue, no PR. |
| **STALE-CITATION** | small | the ADR should cite the changed symbol at `:Symbol` granularity, or a citation is dead/over-broad (`OVER_CITATION`/`DEAD_CITATION`) | **Fix in the causing PR.** Propose the citation edit as a bot-commit / suggested-change on that PR's branch — reconciled in the same unit of work, no separate issue. |
| **DECISION-REVIEW** | rare | the change plausibly alters the ADR's decision AND the ADR is unenforceable (so no enforcement check could have caught it) | **The only thing that becomes work.** One HITL escalation, never batched away, rate-budgeted. |

### Anti-flood / self-healing mechanisms

1. **Idempotent ack (fixes the current re-fire bug).** The `adr-ack` record is keyed on the touchpoint identity `(adr_number, module_path, citation_kind)`, **not** on the PR. Once a touchpoint is acknowledged NOISE, a later *unrelated* touch of the same module does not re-fire it. This is the concrete fix for the current system's re-detection: `AdrTouchpointAuditorLoop` re-computes drift every tick and re-opens/updates the rollup, which is why obsoleted rollups need the `_reconcile_stale_rollups` machinery to chase them closed. An idempotent ack removes the re-fire at the source.
   - **Record format** (append-only JSONL, `<data_root>/diagnostics/adr_ack.jsonl`, following `escape_ledger.jsonl` / `adr_conformance.jsonl` conventions): `ts, adr_number, module_path, citation_kind (bare|symbol), class (noise|stale-citation|decision-review), classifier (churn-suppress|llm-consistent|symbol-rule), pr, notes`. The **idempotency key** is `(adr_number, module_path, citation_kind)`; the newest row wins (compacted like `adr_conformance.jsonl`).
2. **Churn-driven auto-suppression (retires `_SHARED_INFRA_MODULES`).** A module is auto-treated as a dependency pointer — a bare citation to it does not drift — when it is **cited-by ≥ N ADRs AND changed in ≥ M merged PRs without a triaged decision-change** (i.e. every prior touch acked NOISE or its enforcement check stayed green). Derive N/M from the per-PR drift history the auditor already computes plus the `adr_ack` ledger. This is self-tuning: `review_advisor.py` and `_phase.py` (the #10411 modules) enter the suppression set automatically the moment their churn-without-decision-change crosses threshold, with no hand edit. The static `frozenset` becomes a computed set; the allowlist-as-code is retired.
3. **Finding-rate budget on genuine escalations.** A spike in DECISION-REVIEW touchpoints (e.g. a mass ADR-citation refactor) collapses to **ONE meta-signal**, not N escalations — same discipline as the erosion finding-rate budget and the second-order-vitals "single alarm, never batched." A firing is load-bearing precisely because it is rare and un-batched.

---

## Control-theory framing

| Element | Current (ADR-0056) | Proposed |
|---|---|---|
| **Sensor** | "a cited `src/` file changed" (post-merge, ~70% noise) | enforcement-conformance evaluation, scoped, at PR time (primary, ~0% noise); weak citation-classify only for the unenforceable tail (backstop) |
| **Error signal** | raw count of citation-touch drift findings | count of **failing enforcement checks** on Accepted ADRs (decision genuinely violated) + count of **un-acknowledged DECISION-REVIEW** touchpoints in the tail — never raw drift |
| **Actuator** | file issue → triage → resolver bot-PR (separate work) | fix-code-in-the-causing-PR (enforcement FAIL) / suppress-silently (NOISE) / fix-citation-in-PR (STALE) / escalate-one-HITL (genuine) |
| **Feedback** | none — re-detects the same drift forever | churn + acks tighten the NOISE classifier and grow the suppression set; recurring enforcement FAIL past the ADR-0100 attempt budget flips to `adr_reviewer` supersession; the unenforced-debt metric pressures ADRs toward machine-checkable `Enforced by:` |

The loop closes: a green enforcement check is the plant's own claim its decision holds; a red one is the fault signal; the actuator reconciles in-band; and the feedback path makes the noise classifier and the enforcement coverage both improve over time instead of accreting more manual filters.

---

## Module reorientation map (reorient, don't add a 9th piece)

| Module | Today | Becomes |
|---|---|---|
| `adr_conformance.py` (ADR-0100 pure model) | evaluates `Enforced by:` checks post-merge | **PROMOTED to primary.** Gains a PR-diff-scoped evaluation entry point (evaluate only the ADRs whose checks intersect the PR's changed files/tests, not the full ~300s-each sweep) + the unenforced-debt tabulation (already derivable from its `MANUAL`/`SKIPPED` outcomes). |
| `adr_conformance_loop.py` (ADR-0100 caretaker) | post-merge periodic executor, issue-only writes | **PROMOTED + extended.** Keeps the post-merge drift watch; adds the attribution surface (red enforcement check → owning ADR) and emits/updates the single unenforced-debt rollup. Escalation/supersession path unchanged. |
| `adr_drift_triage.py` (`DriftClassification` enum + text-shaping) | pure triage model for the auditor's rollups | **REPURPOSED as the NOISE classifier.** `CONSISTENT` → NOISE (silent ack); `OVER_CITATION`/`DEAD_CITATION` → STALE-CITATION; `REAL_DRIFT` on an *unenforceable* ADR → DECISION-REVIEW. Runs only on the residual tail, not the flood. |
| `adr_drift_triage_llm.py` (LLM wrapper) | triages every rollup | **REUSED, scoped down.** Same structured call; invoked only for tail touchpoints not already resolved by churn-suppression — a fraction of today's volume. |
| `adr_drift_resolver_loop.py` | reads rollups; relabels to `hydraflow-find` / auto-closes CONSISTENT | **REPURPOSED for in-band reconciliation.** The CONSISTENT auto-close becomes the silent `adr-ack` write; the relabel-to-discover-pipeline machinery becomes the STALE-CITATION *fix-in-PR* commit/suggestion on the causing branch instead of minting a separate `hydraflow-find`. |
| `adr_drift_resolver_runtime.py` (LLM adapter) | production backend seam | **REUSED as-is.** Provider dial, CH-6 gate, credit-awareness unchanged. |
| `adr_drift.py` (`compute_drift`, `_SHARED_INFRA_MODULES`, fleet partition) | citation-intersection engine + hand allowlist + fleet batching | **DEMOTED + trimmed.** `compute_drift` survives as the tail backstop's intersection primitive; `_SHARED_INFRA_MODULES` is **RETIRED** in favor of churn-suppression; fleet-batching (#9662) is **RETIRED** — with no per-touchpoint flood there is nothing to batch. |
| `adr_touchpoint_auditor_loop.py` (ADR-0056 detector) | scans merged PRs, mints rollup/fleet issues, re-detects each tick | **ISSUE-MINTING RETIRED.** Its scan/cursor mechanics are repurposed to feed the churn-suppression statistics and the tail sensor; it no longer files `hydraflow-adr-drift` rollups. This is the flood point that closes. |
| `rollup_issue_manager.py` (generic one-issue-per-subject) | used by several caretakers | **REUSED, narrowly.** Backs the single unenforced-debt rollup and the rate-budgeted DECISION-REVIEW escalation — one stable issue each, never per-touchpoint. |
| `plan_touchpoint_expander.py` (ADR-0063 plan-phase enrichment) | surfaces ADR/PR/wiki touchpoints on plan-review failure | **LIGHTLY REUSED.** Orthogonal (plan phase, not drift), but the natural place to surface "this plan touches ADR-00NN — do not break its enforcement check." No behavior change required for v1. |

**Genuinely new** (small, and each replaces something manual): the PR-time scoped enforcement sensor + attribution; the `adr_ack.jsonl` ledger with its idempotency key; the churn-suppression computation; the unenforced-debt metric surface; the finding-rate budget on tail escalations. **Everything else is reuse or retirement** — the net module count goes *down*.

---

## Migration / rollout (no flag day)

1. **Land the debt metric first (read-only, zero risk).** Compute + surface the unenforced-decision count from existing `adr_conformance.evaluate_adrs` output. This ships value on day one and needs no change to the flood pipeline.
2. **Attach the PR-time enforcement sensor advisory.** Model it on #10352: advisory, non-blocking, files nothing that gates a PR; it only annotates ("this PR's diff intersects ADR-00NN's enforced check — status: green/red"). Run it in shadow alongside the existing auditor and compare: it should reproduce every *genuine* decision violation the old system's HITL escalations caught, at a fraction of the issue volume.
3. **Introduce the `adr-ack` ledger + churn-suppression in shadow.** Populate the ledger from live drift computations; compute the auto-suppression set; assert it is a **superset** of today's hand-maintained `_SHARED_INFRA_MODULES` (including the #10411 modules) before it becomes authoritative. This is the safety proof that no currently-suppressed module starts flooding.
4. **Flip the auditor from mint-issues to feed-ledger.** Once the ack ledger + suppression set are authoritative, `AdrTouchpointAuditorLoop` stops filing rollups and instead emits ack records + tail touchpoints. The resolver loop moves from relabel-to-find to fix-in-PR. `_SHARED_INFRA_MODULES` and fleet-batching are deleted in the same PR that proves the churn set covers them.
5. **Author the superseding ADR.** A follow-up ADR supersedes ADR-0056 and extends ADR-0100 with the enforcement-as-primary-signal decision; this proposal is its spec input. Per repo rule, contradicting an Accepted ADR requires that superseding ADR — this doc does not itself enact the supersession.

Each step is independently revertible and observable; there is no single cutover where drift signalling is off.

## Risks

- **Over-trusting a weak `Enforced by:`.** The central risk of the reframe: an `enforced` ADR whose check resolves and passes but does not actually assert the Decision (a tautological or too-narrow test) reads as "conformant" when the decision may in fact have drifted. The coverage ratchet checks *resolution*, not *assertion strength*. Mitigation: (a) the unenforced-debt metric is extended to flag suspiciously-thin checks (e.g. a `pytest:` node that never asserts, by size/coverage heuristic) for sampled human review; (b) `manual`/`decision-of-record` ADRs retain periodic human review regardless; (c) the tail citation-backstop still runs advisory on unenforceable ADRs, so a decision-relevant change there is not wholly invisible. Enforcement-conformance raises precision; it must not be sold as raising it to 100% — a green check is *necessary but not sufficient*.
- **False-suppression of a real decision-change.** Churn-suppression could silence a module that later hosts a genuine decision-relevant change. Mitigation: suppression only ever suppresses the *bare-citation* signal; a `:Symbol`-qualified citation (the granularity an ADR uses when it genuinely owns a symbol) is never suppressed — identical to today's #9176 semantics, now applied automatically. And enforcement-conformance is orthogonal to citation-suppression: an enforced decision is caught by its check no matter how churny its file is.
- **DECISION-REVIEW classifier fail-toward-escalation.** The tail classifier must stay conservative: any residual touchpoint on an unenforceable ADR that the LLM cannot confidently place as NOISE or STALE escalates (LOW_CONFIDENCE → HITL), exactly as `adr_drift_triage`'s current FAIL-CLOSED rule. A wrong "noise" silently loses drift forever; a wrong "escalate" costs a human 30 seconds. The budget caps volume without changing the fail-closed default.
- **Scoped PR-time evaluation cost.** Running enforcement checks per-PR must be *scoped* (only ADRs whose checks intersect the diff), never the full sweep — ADR-0100 deliberately put full execution post-merge because checks run up to 300s each. The sensor evaluates a handful of intersecting checks, or defers to the check's own existing CI result when it is already a required gate.

## Non-goals

- No new merge-blocking gate. The PR-time sensor is advisory (the #10352 hard constraint); enforcement checks that are *already* required gates keep gating — this adds attribution, not new blocks.
- No auto-editing of ADR **Decision** text. STALE-CITATION fixes touch *citations* (the `Enforced by:`/source-citation lines), never the decision prose; a genuine decision change is a human/`adr_reviewer` supersession, as ADR-0100 already holds.
- No retroactive backfill of the ack ledger or debt metric in v1 (prime cursors on install, per `ErosionMetricsLoop` convention).
- No ML / anomaly detection — churn-suppression is a legible counting heuristic; legibility is a feature in a subsystem that has to be trusted when it stays silent.
- This proposal does not itself supersede ADR-0056 or amend ADR-0100; it is the spec for the ADR that would.

## Acceptance criteria

- The unenforced-decision debt count is computed from `adr_conformance.evaluate_adrs` output and rendered on one standing surface; a synthetic ADR set with known `manual`/`decision-of-record`/prose-only members produces the exact count.
- A PR whose diff breaks a real enforcement invariant (e.g. re-introduces a `src → scripts` import against `test_src_does_not_import_scripts.py`) is attributed to the owning ADR and surfaces as a decision-violation signal; a PR that only churns a high-citation shared-infra file (the #10388/#10405/#10406 shape) produces **zero** issues.
- The churn-suppression set is demonstrably a superset of today's `_SHARED_INFRA_MODULES` — including `review_advisor.py` and `review_phase/_phase.py` (#10411) — before it becomes authoritative.
- An acked NOISE touchpoint does not re-fire on a later unrelated touch of the same module (idempotency key verified against a two-touch synthetic sequence — the exact re-fire the current system exhibits).
- A synthetic spike of DECISION-REVIEW touchpoints produces exactly ONE meta-escalation, not N (finding-rate budget).
- Shadow run: the enforcement sensor reproduces every genuine decision-violation HITL the old auditor escalated, at materially lower total issue volume.

## Open questions (for planning / the superseding ADR)

- Thresholds N (cited-by-≥N-ADRs) and M (changed-in-≥M-PRs): derive from the live drift history, or set conservatively and let feedback tune?
- Does the PR-time sensor attach as a review-phase advisory step (inside the existing review pipeline) or as a standalone advisory workflow like #10352? The review-phase step gets richer diff context; the workflow is more isolable.
- Should the "weak/tautological enforcement" heuristic (Risks §1) ship in v1 or as a fast-follow once the debt metric exists?
- Where does the tail citation-backstop's advisory annotation live so it stays visible but never becomes lane work — PR comment, review summary, or ledger-only?
