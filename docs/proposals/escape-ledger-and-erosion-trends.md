# Escape ledger + erosion trend surfaces

**Status:** proposal (2026-07-23). **Origin:** the two falsification instruments named in *When Code Becomes FLUID* Ch 16 — the gauges that would detect the factory degrading while its gates stay green. Epic #10104 closed half of the outer-loop gap (per-change erosion sensing); this proposal closes the other half and adds the missing trend surfaces.

## The gap

Two claims the factory publishes cannot currently be checked from its own instruments:

1. **Nothing measures what escapes the gauntlet.** Sentry incidents, reverts, and bug reports become triaged work (SentryLoop → `/hf.issue`), but no record links a discovered defect back to the merge that shipped it. There is no escape rate, no time-to-detection, and no evidence that each escape terminated in an encoding. The Faros axis the book confronts head-on (unreviewed merges) is answerable only with this ledger.
2. **Erosion senses per-change but surfaces no trend.** `erosion.spread` (#10105) and `erosion.scatter` (#10106) file above-baseline findings into triage, but the codebase-scale question ("is entanglement growing month over month?") has no standing answer — the Ch 16 retrospective (files-touched, modules-crossed, duplication density, month by month) was a one-off script, not an instrument. Duplication density is explicitly out of v1 scope per `erosion/scatter.py`'s own docstring.

## Part 1 — Escape ledger

### Definition (decided)

An **escape** is a defect discovered *after* a change passed the gauntlet and merged to the base branch. Detection sources (v1):

- revert commits touching a prior merge
- hotfix PRs whose body/commits reference a prior merge
- bug-labeled issues whose eventual fix traces to a prior merge (`fixes #N` chains, blame intersection)
- regression tests added to pin a post-merge failure
- Sentry incidents attributed to a merge (via the existing SentryLoop flow)

**Not escapes** (boundary, decided): anything caught pre-merge by the gauntlet, and main-CI breaks caught immediately on merge — those are the gates functioning, and counting them dilutes the "escaped the instruments" meaning.

### Ledger record (append-only JSONL, `<data_root>/diagnostics/escape_ledger.jsonl`, following `factory_metrics.jsonl`)

```
id, detected_at, detection_source (sentry|revert|hotfix|bug-issue|regression-pin),
detection_ref, originating_pr, originating_merge_sha, merged_at,
time_to_detection_hours, attribution_method (revert-parse|fixes-chain|
regression-pin|blame-intersect|agent-research), attribution_confidence
(high|medium|low), encoded_as (refs: regression test / stored lesson /
detector / ADR / none-yet), notes
```

### Attribution (hybrid, decided)

Mechanical first: revert parsing, `fixes #N` chains, regression-pin references, blame intersection of the fix diff against candidate merges. Agent-assisted research for Sentry-sourced escapes (extend the existing SentryLoop agent invocation to also emit an attribution record). Low-confidence rows escalate through the existing HITL surface for a human label; attribution never blocks anything.

### Addenda (issue #10498, decided)

Hardening found by triaging a false-positive `bug-issue` row:

- **A behaviour-neutral `fix(...)` commit is not an escape.** The `bug-issue` branch of `escape.detect._classify` is gated on the repo's existing `false_close.has_skip_regression` opt-out trailer (the same P10.6/P10.7 signature, reused rather than reimplemented). A commit that declares `Skip-Regression: <why>` — e.g. a docs-only diagram refresh — never produces a candidate, even if its subject carries a `fix(...)` prefix. The gate is scoped to the `bug-issue` branch only: a revert or hotfix that happens to also carry the trailer is still recorded.
- **`originating_pr` means the merge that introduced the defect — never the issue/PR a commit closes.** A GitHub closing keyword (`Fixes`/`Closes`/`Resolves #N`) points downstream at resolved work, not upstream at the introducing merge, so `escape.detect` never writes it to `EscapeCandidate.originating_pr`/`EscapeRecord.originating_pr`. The closed reference stays visible as `originating_ref` (`"#N"`) and still selects `attribution_method: fixes-chain`. `originating_pr` is populated only by a writer with a genuine introducing-PR pointer — today that is `audit.crosslink`, which sets it from a real `sample.pr_number` paired with a merge sha.
- **A terminal state without rewriting the ledger.** `EscapeLedger` stays append-only (it never rewrites a line), so a human resolution — confirmed attribution, or an `encoded_as` disposition — is recorded by `EscapeLedger.append_resolution(id, encoded_as=..., attribution_confidence=..., notes=...)`, which appends a NEW row sharing the original's id and carries forward every other field. Every derived read collapses to one row per id via latest-appended-row-wins: `escape.metrics.latest_by_id` (the pure collapse) and `EscapeLedger.read_latest` (the ledger-level read used by `EscapeLedgerLoop._render_reports`/`_surface_findings`). `read_all`/`existing_ids` are unaffected — dedup-by-id already collapses to one entry regardless of how many rows share that id.

### Loop shape

`EscapeLedgerLoop` — read-only caretaker (ADR-0029 shape), **Pattern B** like `ErosionMetricsLoop`: it senses and records, never opens fix PRs (the escape already became work through normal triage; the ledger is bookkeeping about the instruments, not one of them). Cursor conventions per `ErosionMetricsLoop`: prime on fresh install, no implicit back-analysis; a one-time explicit backfill command may be provided separately.

### Metrics and surfaces

- **escapes per 100 merges** (rolling 30-day and monthly series) — the headline falsification metric
- **time-to-detection** (median, p90) by detection source
- **encoded-vs-unencoded** count: every escape should terminate in an encoding (test/lesson/detector); unencoded escapes older than a threshold get filed as `hydraflow-find` issues
- Regenerated report `docs/arch/generated/escape-ledger.md` (following `loop-fitness.md`), plus a dashboard panel

## Part 2 — Erosion trend completion (v2 of epic #10104)

1. **Duplication-density sensor**: near-duplicate block density per KLOC (jscpd-class detection — the candidate `erosion/scatter.py` v1 explicitly deferred). Same purity contract as `erosion.spread`: pure `compute` over explicit inputs, thin git adapter.
2. **Monthly trend rollup**: percent of changes crossing ≥3 modules, mean files-touched per change, duplication density, scatter finding counts — persisted as a time series and rendered to `docs/arch/generated/erosion-trends.md` + a dashboard sparkline. This makes the Ch 16 retrospective a standing instrument instead of a one-off.
3. **Baseline and alarm-rate governance**: thresholds under the ADR-0104 ratchet precedent, with an explicit finding-rate budget (dedup + cooldown). Rationale: an instrument that over-files gets rationally dismissed, and the adjudication discipline only holds if alarm rates are governed.

## Non-goals

No merge blocking, no auto-remediation, no severity taxonomy in v1, no cross-repo scope (v1 measures the factory repo itself). The ledger measures the instruments; it is not a gate.

## Acceptance criteria

- A merged revert / hotfix / regression-pin / attributed Sentry incident each produce exactly one ledger row with a populated `time_to_detection_hours` and an attribution method + confidence
- `escapes per 100 merges` and time-to-detection series are queryable and rendered in the generated report and dashboard
- Duplication density computes over synthetic inputs with no git dependency (unit-testable pure core)
- Erosion trend report shows monthly series for all four trend metrics
- Finding-rate budget demonstrably caps issue filing under a synthetic flood
- Fresh-install runs prime cursors without back-analysis

## Open questions (for planning/decomposition)

- Backfill: run the ledger retroactively over the public history (the Ch 16 window) as a one-time command, or start from cursor-prime only?
- Severity classification: worth a v2 field once rows exist, or permanently out?
- Should `encoded_as: none-yet` aging thresholds escalate to HITL rather than filing `hydraflow-find`?
