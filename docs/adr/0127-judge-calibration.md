# ADR-0127: Judge calibration — scoring a judge's verdicts against outcomes with proper scoring rules

- **Status:** Proposed
- **Date:** 2026-08-03
- **Related:** [ADR-0125](0125-mutation-gauntlet-gate-sensitivity.md) (Mutation gauntlet — gate sensitivity) and [ADR-0126](0126-golden-baseline-finder-calibration.md) (Golden-baseline finder calibration — finder noise) — the two shipped siblings this completes into a trilogy, same pure-core + injected-seam + append-only-ledger + read-only-endpoint shape, measuring the *third* quantity (judge quality); the escape ledger (#10367, `src/escape/ledger.py`) — the outcome source this resolves ground truth from; the sampled re-audit (#10370, `src/audit/store.py`) — the sibling "upheld disagreement" outcome signal, a documented follow-up source; the judge-independence coverage ledger (#10371/#10832, `src/judge_independence.py`) — the *dissent* instrument this complements with a *calibration* one; [ADR-0044](0044-hydraflow-principles.md) (the HydraFlow principles + review-pipeline workflow whose PostVerifyAdvisor is the first calibrated judge)
- **Enforcement:** enforced
- **Enforced by:** `pytest:tests/test_judge_calibration.py`
- **Binds:** factory
- **Addresses:** #10836 (judge calibration — the third quality-machinery instrument); consumes the escape ledger (#10367) as its outcome oracle and complements judge-independence dissent (#10371/#10832) with a proper-scoring calibration axis

> **This is a Proposed ADR — a design ruling for decision, not an accepted commitment.** It records the methodology and, deliberately, what is *real today* (this first slice) versus *deferred* to later phases. The instrument is a pure engine + ledger + a read-only endpoint + one fail-soft recording call, not a background loop. Accept, amend, or reject.

## Context

The factory runs *judges* — the PostVerifyAdvisor that approves or vetoes a change, the reviewer that estimates risk, the mid-flight advisor consulted on a call. Some of them state a **confidence**. But a verdict with a confidence is a **forecast**, and the factory has never checked whether those forecasts are any good. A judge that says "APPROVE, 95% confident" and is wrong a third of the time is not a 95% judge; a judge that vetoes everything at 60% confidence is not discriminating at all. Without measuring this, the factory trusts its judges by assertion.

The two shipped siblings measure the other two halves of "is the quality machinery real". The mutation gauntlet (ADR-0125) measures **gate sensitivity** — inject a known fault, does the gate go red? The finder calibration (ADR-0126) measures **finder noise** — what does a generative finder flag against a known-clean baseline? The missing third is **judge quality** — when a judge passes or vetoes with a stated confidence, is that confidence earned?

The right tool is a **proper scoring rule**: a scoring function a forecaster minimizes *only* by reporting its true probability, so it rewards honesty and punishes both over- and under-confidence. The two canonical ones — the **Brier score** (mean squared error of the probability) and the **log score** (cross-entropy) — are decades-old and well understood. The insight #10836 insists on is that a single score conflates two *separable* things:

- **Calibration** — does 80% confidence mean 80% correct? A judge can be perfectly calibrated and *useless* (always says 50%, right half the time).
- **Discrimination** — does the judge separate good changes from bad *at all*? A judge can discriminate sharply and be *badly miscalibrated* (right ordering, wrong numbers).

They are orthogonal, so the instrument must report **both**, never a blended single number.

## Decision

Introduce **judge calibration**: a pure engine that joins each judge's recorded verdicts to their eventual outcomes, scores the forecasts with the Brier and log rules, and decomposes the result into the calibration and discrimination axes — plus a thin fail-soft recorder wired at one judge site and a read-only diagnostics endpoint.

### Ruling 1 — a verdict + confidence is a forecast of P(good)

`src/judge_calibration.py:to_forecast` maps a `(verdict, confidence)` pair to a single predicted probability the change is good: `PASS @ 0.9 → 0.9`, `FAIL @ 0.9 → 0.1` (90% sure it is bad = 10% good). Confidence is clamped to `[0, 1]` so a malformed record can never produce a forecast outside the unit interval.

### Ruling 2 — score with BOTH proper rules, decomposed into two axes

`src/judge_calibration.py:brier_score` and `:log_score` are the overall proper scores (lower is better; the log score clips into `[eps, 1-eps]` so confident-wrong is large-but-finite, never `+inf`). The **calibration** axis is the reliability curve `:calibration_curve` (per-decile stated-vs-empirical rate) and its scalar summary `:calibration_error` (population-weighted expected calibration error). The **discrimination** axis is `:discrimination` — the AUC, `P(predicted_good(good) > predicted_good(bad))` with ties at half. `src/judge_calibration.py:score_judge` bundles all of it into a `JudgeScore` reporting the two axes *separately*, exactly because a judge can be well-calibrated and useless, or sharp and miscalibrated.

### Ruling 3 — honest degeneracy, never a crash or a faked signal

Zero resolved forecasts → every scalar is `None` and `low_confidence` is set (the "no data yet" row), never a divide-by-zero. All-good or all-bad outcomes → discrimination is *undefined* (`None`, `discrimination_undefined` flagged), never faked as 0.5. A thin resolved sample (below `MIN_CONFIDENT_RESOLVED`) is flagged `low_confidence` so a 3-sample "perfect" judge is not read as proven. This is asserted across the unit suite on hand-computed distributions.

### Ruling 4 — outcomes resolved from the escape ledger, behind an injected seam

Ground truth is "did the change turn out good?", and the escape ledger (#10367) already answers the negative: a merge that was reverted / hotfixed / regression-pinned / bug-filed is an *escape* — whatever judge passed it was wrong. `src/judge_calibration.py:resolve_outcomes` keys a verdict's subject to a PR (`subject_for_pr` → `"pr:<n>"`, the escape ledger's `originating_pr`) and rules:

- a subject with an attributed escape → **bad**, immediately (an escape is definitive);
- an escape-free subject whose latest verdict is older than the **grace window** → **good**;
- a too-recent escape-free subject → **unresolved**, excluded (an escape could still surface).

The grace window is **7 days** (`DEFAULT_GRACE_WINDOW`): escapes surface with a lag (a revert lands in hours, a filed bug in days), so calling a fresh merge "good" the instant it lands would over-credit every judge that passed it. Seven days clears the bulk of the escape-detection distribution while still resolving verdicts within a week. The resolution runs behind the `src/judge_calibration.py:OutcomeResolver` protocol; `:EscapeLedgerOutcomeResolver` is a *data-in* adapter (it holds escape records, not the ledger file), so the endpoint owns the I/O and the engine stays pure. The sampled-audit "upheld disagreement" signal (#10370) is a documented second outcome source, deferred.

### Ruling 5 — persistence is additive and fail-soft at ONE judge site

Confidence is elicited but was never persisted per-verdict in a joinable record, so this slice adds that. The PostVerifyAdvisor is the clearest judge-with-a-verdict: its `APPROVE`/`VETO` is a genuine PASS/FAIL merge call. Additively, `PostVerifyResult` gains an optional `confidence` field (defaulted `None`, so every existing payload still validates unchanged) and its prompt now elicits a calibrated self-estimate. At the emit site the advisor best-effort records the judge's **RAW** verdict + confidence (before any advisory downgrade — calibration scores the judge's true call, not the policy-adjusted one) via `src/judge_calibration.py:record_verdict`. That recorder is wrapped fail-soft: a ledger write error is swallowed and logged, and can NEVER change the verdict, delay it, or raise into the review pipeline. An absent confidence is honestly skipped, never fabricated. The advisor's verdict logic is untouched. The reviewer precheck (`PRECHECK_CONFIDENCE`, `src/precheck.py`) already carries a numeric confidence but emits a *risk/escalate* triage rather than a binary merge verdict, so wiring it is deferred until its verdict semantics are mapped — stated, not skipped.

### Ruling 6 — an engine + ledger + read-only endpoint, not a loop

Verdicts persist append-only to `<data_root>/calibration/judge_verdicts.jsonl` (sharing the `calibration` subdir with the finder floors), reusing `src/jsonl_ledger.py:AppendOnlyJsonlLedger`; rows are never deduped (a judge may verdict the same subject across retries, each its own datum). `GET /api/diagnostics/judge-calibration` reads the verdict ledger, resolves outcomes from the escape ledger, and returns per-judge `JudgeScore` rows — read-only, and fail-soft: an escape-ledger read failure degrades to *no outcomes* (every judge "no data yet") rather than falling through to an empty escape set, which would silently resolve every past-grace verdict as good and over-credit judges exactly when the bad-outcome signal is down; an empty verdict ledger yields an empty `judges` list, never a 500. This is an engine, like the two siblings — **not** a background loop: no seven-checkpoint wiring, no MockWorld shim, no `functional_areas.yml`.

## What is real today (this first slice) vs deferred

**Real:** the pure core (`Verdict`, `JudgeVerdictRecord`, `Outcome`, `ResolvedForecast`, `CalibrationBin`, `JudgeScore`; `to_forecast`, `resolve`, `brier_score`, `log_score`, `calibration_curve`, `calibration_error`, `discrimination`, `score_judge`, `score_all`); grace-window outcome resolution (`resolve_outcomes`, `escaped_subjects`) behind the `OutcomeResolver` seam + `EscapeLedgerOutcomeResolver`; the append-only `JudgeCalibrationLedger` + fail-soft `record_verdict`; the additive PostVerifyAdvisor recording wire (raw verdict + confidence, fail-soft); the `GET /api/diagnostics/judge-calibration` endpoint; and the full unit + route + wiring test suite pinning the statistics on known distributions, the two-axis independence, every degenerate case, the ledger round-trip, and the fail-soft guarantee.

**Deferred (honestly):**

- **No frontend panel** in this slice — backend + endpoint only. A reliability-diagram panel (the calibration curve + the two-axis summary) is a clean follow-up.
- **The reviewer precheck** as a second judge site, once its risk/escalate output is mapped to a binary verdict; and the **mid-flight advisor** consult (`{reasoning, recommendation, confidence}`), which is dispatched from inside the executor session and needs its own interception seam.
- **The sampled-audit "upheld disagreement" signal** (#10370) as a second outcome source alongside the escape ledger, for richer ground truth than reverts/hotfixes alone.
- **A slow-cadence calibration loop** that recomputes scores on a schedule and files a `hydraflow-find` when a judge goes miscalibrated or non-discriminating. This slice only *produces* the score substrate; it does not watch it.
- No scenario / sandbox-e2e layer is added, deliberately: there is no new loop, no label transition, and no UI/docker wiring to exercise — the deliverable is a pure engine + ledger + a read-only endpoint + one fail-soft recording call, whose whole contract is covered by fast unit + route + wiring tests. Those layers become load-bearing when the panel and the calibration loop land.

## Consequences

- **Positive:** every judge that states a confidence can now be scored against reality on two orthogonal axes, so a judge can no longer be trusted by assertion — a miscalibrated or non-discriminating judge becomes visible and measurable. The escape ledger gains a second consumer, tightening the loop between "a defect escaped" and "which judge's confidence was wrong". The instrument completes the quality-machinery trilogy (gate sensitivity + finder noise + judge quality) with a shared, recognizable shape.
- **Cost:** a score is only as good as its outcome oracle. The escape ledger under-counts (a silent defect that never triggers a revert/hotfix/bug is not an escape), so an unresolved-but-actually-bad change resolves as *good* after the grace window — the calibration is optimistic by exactly the escape ledger's false-negative rate. The sampled-audit source (deferred) partly addresses this. The 7-day grace window is a planning-picked v1, tunable as escape time-to-detection data accumulates.
- **Negative / watch:** the added `PostVerifyResult.confidence` field depends on the advisor model actually returning a calibrated self-estimate; until it does, nothing records (honest, but the ledger stays empty). Only one judge site is wired in this slice, so the panel speaks for the PostVerifyAdvisor alone until the deferred sites land — a boundary stated rather than blurred.
