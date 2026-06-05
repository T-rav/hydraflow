# LogIngestLoop — self-log error/warning ingestion (LLM-free)

**Status:** Implemented · **Date:** 2026-06-04 · **Loop:** `log_ingest` (L, interval 4h)
**Pattern:** Caretaker loop (ADR-0029) · Kill-switch (ADR-0049)

## Problem

HydraFlow emits structured JSON logs but nothing turns recurring runtime
errors/warnings in its *own* server log into fixable work. SentryLoop covers
externally-reported errors; this loop covers the local server log so a recurring
`ERROR`/`WARNING` becomes a GitHub issue and flows through the normal
triage → plan → implement → review → merge pipeline. The pipeline's agents do
the fixing — this loop is **pure-Python and LLM-free**.

## Design

`src/log_ingest_loop.py` — `LogIngestLoop(BaseBackgroundLoop)`, worker
`log_ingest`, default interval `log_ingest_interval` (14400s / 4h),
`run_on_startup=True`.

`_do_work` per cycle:

1. **Kill-switch / config gate.** `enabled_cb` off → `{"status":"disabled"}`;
   `log_ingest_loop_enabled` False → `{"status":"config_disabled"}`.
2. **Resolve log files** from `log_ingest_log_files` (comma-sep; relative paths
   resolve against `data_root`, default `logs/hydraflow.log`).
3. **Cursor-from-now.** Per-file byte-offset cursor persisted in
   `StateData.log_ingest_cursor` (keyed by resolved path). First time a file is
   seen → prime the cursor to current EOF and file nothing
   (`{"status":"primed"}`). Subsequent cycles read only bytes appended past the
   cursor. Truncation/rotation (size < stored offset) → restart from byte 0.
   This avoids back-filling / re-filing already-fixed historical errors.
4. **Parse + filter.** JSON lines `{ts, level, msg, logger}`. Keep
   `ERROR`/`CRITICAL`/`WARNING`. **Self-reference guard:** skip the loop's own
   loggers (`hydraflow.log_ingest`, `hydraflow.log_ingestion`) so it never
   ingests its own activity (no feedback loop).
5. **Cluster by signature.** `normalize_signature` strips timestamps, UUIDs,
   issue/PR `#N`, file paths, hex/uuid hashes, quoted strings, and bare numbers
   (incl. numbers glued to units like `70ms`/`5xx`) to placeholders → a stable
   key. `CRITICAL` folds into `ERROR`. Count occurrences per signature.
6. **Importance filter.** ERROR always a candidate; WARNING only at/above
   `log_ingest_warning_min_count` (default 50). Drop clusters matching any
   `log_ingest_benign_patterns` substring (case-insensitive, message OR logger).
   Seeded allowlist: `adapter pending`, `auth failed`/`authentication failed`,
   `repository not found`, `credit`/`creditexhausted`, and the loop's own logger.
7. **Dedup.** Per signature-hash (`sha1(level:signature)[:16]`): hot cache →
   `DedupStore` (`dedup/log_ingest_filed.json`) → open GitHub issues carrying
   the hidden marker `<!-- [log-ingest:<sighash>] -->`.
8. **Hard cap + priority.** File ≤ `log_ingest_max_issues_per_run` (default 3),
   ERROR-first then count-desc. Dedup is resolved *before* the cap so an
   already-filed cluster never burns cap budget. Capped + dropped counts are
   logged (no silent truncation).
9. **File issue** via `PRManager.create_issue`. Title = `[log-ingest] LEVEL:
   <signature>` (truncated); body = level + count + representative RAW line +
   logger + suspected source file (parsed from a `.py` reference) + the marker.
   Labels = `find_label` (enters the pipeline) + `log_ingest_label`
   (`hydraflow-log-ingest`). **0-sentinel guard:** if `create_issue` returns 0,
   do NOT record the dedup key — retry next cycle (#9242 pattern).
10. **Advance cursors** to new EOF; return `{filed, skipped, dropped, capped,
    files_primed, clusters}`.

## Config (`src/config.py`)

| Knob | Env | Default | Bounds |
|---|---|---|---|
| `log_ingest_loop_enabled` | `HYDRAFLOW_LOG_INGEST_LOOP_ENABLED` | `True` | bool |
| `log_ingest_interval` | `LOG_INGEST_INTERVAL` | `14400` | 300–86400 |
| `log_ingest_warning_min_count` | `LOG_INGEST_WARNING_MIN_COUNT` | `50` | 1–100000 |
| `log_ingest_max_issues_per_run` | `LOG_INGEST_MAX_ISSUES_PER_RUN` | `3` | 1–20 |
| `log_ingest_benign_patterns` | `HYDRAFLOW_LOG_INGEST_BENIGN_PATTERNS` | seeded allowlist | str (csv) |
| `log_ingest_label` | `HYDRAFLOW_LOG_INGEST_LABEL` | `hydraflow-log-ingest` | str |
| `log_ingest_log_files` | `HYDRAFLOW_LOG_INGEST_LOG_FILES` | `logs/hydraflow.log` | str (csv) |

## Wiring touchpoints

- State: `StateData.log_ingest_cursor` + `state/_log_ingest.py`
  (`get/set_log_ingest_cursor`) mixed into `StateTracker`.
- Label: `log_ingest_label` added to `prep.HYDRAFLOW_LABELS` (created by
  `ensure_labels_exist`; `prep._label_names` normalises the str field).
- Loop wiring (all six source-of-truth lists): `service_registry.py`
  (import + field + construct + kwarg), `orchestrator.py` `_bg_loop_registry`
  + `_supervise_loops` factories, `dashboard_routes/_control_routes.py`
  `_bg_worker_defs`, `dashboard_routes/_common.py` `_INTERVAL_BOUNDS`,
  `ui/src/constants.js` `BACKGROUND_WORKERS` + `EDITABLE_INTERVAL_WORKERS`,
  scenario catalog `loop_registrations.py`, and
  `tests/orchestrator_integration_utils.py`.
- Functional area: `docs/arch/functional_areas.yml` (caretaking).

## Test pyramid

- **Unit** (`tests/test_log_ingest_loop.py`): disabled no-op, first-run prime
  (no filing), normalisation/clustering, ERROR-always + WARNING≥threshold,
  benign drop (message + logger), dedup (hot-cache/store + open-issue marker),
  rate-cap + capped reporting, create_issue==0 guard (+ retry), self-reference
  guard, cursor advance + rotation restart.
- **MockWorld scenario** (`tests/scenarios/test_log_ingest_scenario.py`,
  `scenario_loops`): full tick against the real `FakeGitHub` PRPort +
  `StateTracker` — prime → file → marker → second-tick dedup; disabled no-op.
- **Sandbox e2e:** deferred follow-up (write an `sNN_log_ingest_*` sandbox
  scenario that seeds a server log with recurring errors and asserts a filed
  issue, mirroring `s42_sentry_ingest_*`).

## Why LLM-free

Clustering is deterministic string normalisation; importance is count + level
thresholds; dedup is a hash + marker scan. The expensive reasoning (root cause,
fix) is the pipeline's job. Keeping the loop LLM-free makes it cheap to run
every 4h and impossible to feedback-loop on its own credit/agent output.
