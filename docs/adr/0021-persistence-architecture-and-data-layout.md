# ADR-0021: Persistence Architecture and Data Layout

**Status:** Accepted
**Enforced by:** tests/test_state_persistence.py, tests/test_event_persistence.py, tests/test_data_migration_d2.py
**Date:** 2026-02-28

## Context

HydraFlow must persist state across process restarts, track active issues through
the pipeline, store event history, and organise logs/plans/memory/metrics for each
managed repository. The persistence layer must support:

- **Crash recovery**: if the orchestrator is killed mid-run, it must resume
  without re-processing completed work or losing track of in-flight issues.
- **Multi-repo isolation**: when a supervisor spawns one HydraFlow process per
  repository, each process must write to its own data directory without collisions.
- **Operational visibility**: dashboards and CLI tools need structured access to
  metrics snapshots, event streams, and session history.
- **Configuration flexibility**: operators must be able to relocate the data
  directory (e.g. to a mounted volume in Docker) without code changes.

Prior to formalising this decision, the data layout had grown organically. This ADR
captures the current architecture and makes the conventions explicit so that future
features (e.g. multi-repo dashboard aggregation, remote state backends) build on a
documented foundation.

## Decision

All HydraFlow persistent data lives under `config.data_root`, which defaults to
`<repo_root>/.hydraflow/`. The data root is resolved at startup with the following
precedence:

1. `HYDRAFLOW_HOME` environment variable (highest priority).
2. Explicit `data_root` field in `HydraFlowConfig`.
3. Default: `<repo_root>/.hydraflow/`.

Full config load order is: Pydantic defaults, config file, env vars, CLI args.
Path resolution runs via the `resolve_defaults` validator in seven steps:

1. `_resolve_base_paths` — repo_root, worktree_base, data_root
2. `_resolve_repo_and_identity` — repo slug, gh_token, git identity
3. `_resolve_repo_scoped_paths` — state_file, event_log_path, config_file
4. `_apply_env_overrides` — env-var overrides for labels, tokens, etc.
5. `_apply_profile_overrides` — grouped tool/model defaults for profiles
6. `_harmonize_tool_model_defaults` — tool and model consistency
7. `_validate_docker` — Docker configuration validation

### Data layout

> **Note:** The layout below reflects the target architecture mandated by
> ADR-0010 (Worktree and Path Isolation Architecture). `log_dir`, `plans_dir`, and `memory_dir` remain flat under
> `data_root/` in the current implementation — see [^1].

```
<data_root>/                        # default: <repo_root>/.hydraflow/
  config.json                       # Persisted config snapshot
  <repo_slug>/                      # Per-repo namespace (owner-repo)
    state.json                      # StateTracker crash-recovery state
    events.jsonl                    # EventBus append-only event log
    sessions.jsonl                  # Session history
    logs/                           # Transcript and log files
    plans/                          # Saved implementation plans
    memory/                         # Memory and review-insight files
    metrics/                        # Per-repo metrics
      snapshots.jsonl               # Dashboard-consumable metric snapshots
  runs/                             # Run artifacts
  manifest/                         # Codebase manifest snapshots
  cache/                            # Ephemeral caches
  verification/                     # Verification artifacts
  dedup/                            # DedupStore JSON files — one per caretaker loop (e.g. sentry_filed.json, flake_tracker.json)
  diagnostics/                      # Factory-level time-series telemetry (factory_metrics.jsonl); served by /api/diagnostics/* routes
  visual-reports/                   # Generated visual report artifacts (screenshots, charts) produced by the VisualReportLoop
```

[^1]: `log_dir`, `plans_dir`, and `memory_dir` are flat under `<data_root>/`
in the current implementation (`config.py` properties return `data_root / "logs"`
etc.). ADR-0010 (Worktree and Path Isolation Architecture) mandates migrating them
to `<data_root>/<repo_slug>/logs/` etc. The layout tree above documents the target
structure; the derived-paths table documents current behaviour.

### Persistence guarantees

- **Atomic writes**: `StateTracker.save()` uses `atomic_write()` (from
  `file_util`) to write `state.json`, preventing corruption from partial writes
  or crashes mid-flush.
- **Immediate persistence**: every state mutation calls `save()` immediately; there
  is no batching or deferred flush.
- **Pydantic validation on load**: `StateTracker.load()` deserialises with
  `StateData.model_validate()`. Corrupt or unreadable state files are reset to
  empty defaults and logged, rather than crashing the process.
- **Automatic migration**: legacy `bg_worker_states` entries are migrated to the
  newer `worker_heartbeats` schema on first load.

### Config snapshot (`config.json`)

An optional `config.json` at `data_root / "config.json"` persists the current
`HydraFlowConfig` as a JSON snapshot. Persistence is disabled by default
(`config_file = None`); operators opt in by setting `config_file` explicitly.
When present, `load_config_file()` reads it at startup and `save_config_file()`
writes it on hot-config updates.

### Session history (`sessions.jsonl`)

`sessions.jsonl` is an append-only JSONL file that records one `SessionLog`
entry per pipeline session (plan, implement, review). It lives alongside
`state.json` at `repo_data_root / "sessions.jsonl"` and is managed by
`StateTracker` (via `_session.py`). Legacy flat-layout files at
`data_root / "sessions.jsonl"` are automatically migrated to the repo-scoped
location on first load (see `_resolve_repo_scoped_paths` in `config.py`).

### Multi-repo namespacing

- Per-repo artifacts are scoped under `data_root/<repo_slug>/` via
  `_resolve_repo_scoped_paths()` in `config.py`, where `repo_slug` is
  `config.repo.replace("/", "-")`. State, events, and sessions are fully
  repo-scoped today; `log_dir`, `plans_dir`, and `memory_dir` remain flat
  under `data_root/` in the current implementation — see [^1].
- `config.repo_data_root` provides a general-purpose repo-scoped subdirectory
  at `data_root / repo_slug`.
- The supervisor spawns isolated processes per repo with separate `HYDRAFLOW_HOME`
  values, giving each process its own `data_root`.
- Worktrees are scoped under `worktree_base / repo_slug / issue-{N}` to prevent
  collisions between same-numbered issues across repositories.

### Derived paths

The following `HydraFlowConfig` properties derive directories from `data_root`:

| Property | Path |
|----------|------|
| `config_file` | `None` by default (persistence disabled); conventional location `data_root / "config.json"` when opted in |
| `repo_data_root` | `data_root / repo_slug` |
| `state_file` | `data_root / repo_slug / "state.json"` |
| `event_log_path` | `data_root / repo_slug / "events.jsonl"` |
| `sessions.jsonl` (no config property; implicit path) | `repo_data_root / "sessions.jsonl"` |
| `log_dir` | `data_root / "logs"` [^1] |
| `plans_dir` | `data_root / "plans"` [^1] |
| `memory_dir` | `data_root / "memory"` [^1] |

All paths can be individually overridden via their respective config fields,
but the defaults ensure a single `data_root` change relocates everything.

## Consequences

**Positive:**

- **Single knob relocation**: setting `HYDRAFLOW_HOME` or `data_root` moves all
  persistent data, which is essential for Docker volume mounts and CI environments.
- **Crash resilience**: atomic writes and Pydantic-validated loads mean the
  orchestrator can be killed at any point and resume cleanly.
- **Multi-repo safety**: repo-slug namespacing in metrics and worktrees prevents
  data collisions when multiple repos are managed from a shared filesystem.
- **Structured layout**: dedicated subdirectories for logs, plans, memory, and
  metrics make it straightforward to add retention policies, backup scripts, or
  dashboard queries targeting specific data categories.

**Negative / Trade-offs:**

- **Single-file state bottleneck**: `state.json` is a single file rewritten on
  every mutation. This is adequate for current throughput but would not scale to
  hundreds of concurrent issues without moving to a database or partitioned state.
- **No built-in replication**: the data directory is local-only. High-availability
  setups require external solutions (e.g. shared NFS, object-store sync).
- **Flat event log**: `events.jsonl` grows without bound until rotation triggers
  (configurable via `event_log_max_size_mb` and `event_log_retention_days`). Large
  deployments should tune these values.
- **Implicit directory creation**: subdirectories are created on first use rather
  than at startup, which can obscure the full layout until the system has exercised
  all code paths.

## Alternatives considered

- **SQLite for state**: would remove the single-file bottleneck and enable
  concurrent reads, but adds a dependency and complicates atomic snapshot export.
  Not justified at current scale.
- **Per-issue state files**: would reduce write contention, but complicates
  querying across issues and makes crash recovery harder (must scan many files).
- **Remote state backend (S3/Redis)**: would enable multi-instance deployments,
  but introduces network failure modes and latency. Deferred until there is a
  concrete multi-instance requirement.
- **Embedded Dolt state backend** (briefly implemented, removed 2026-04-24):
  `DoltBackend` versioned `state.json`, dedup sets, and insight stores via the
  embedded `dolt` CLI. It was opt-in (active only when `dolt` was on PATH) and
  never installed in production containers or EC2, so the file fallback was the
  de-facto path everywhere except one developer machine. Removed because the
  dual-path branches in seven consumers carried real maintenance cost for a
  feature that hadn't earned an ADR or a deployment.

## Amendment (2026-06-08): repo-scope operational stores under the shared-data-root model (D2)

**Context.** The original "Multi-repo isolation" guarantee above assumed the
supervisor spawns *one process per repo, each with its own `HYDRAFLOW_HOME` →
its own `data_root`* (ADR-0009). Under that model, stores resolved via
`config.data_path(...)` (flat, under `data_root`) never collided — each repo had
a private `data_root`. The multi-repo **dashboard** model (ADR-0007/0038) breaks
that assumption: a single host process holds a `RepoRuntimeRegistry` of repo
runtimes that **share one `data_root`** (the deployment sets `HYDRAFLOW_HOME`).
Under a shared `data_root`, the flat per-repo operational stores collide across
repos (e.g. issue #42's run artifacts from repo A overwrite repo B's).

`state.json`, `events.jsonl`, and `sessions.jsonl` were already repo-scoped
(`_resolve_repo_scoped_paths`). This amendment extends that scoping to the
remaining per-repo *operational* stores.

**Decision.** The following stores move from flat `data_path(...)` to
repo-scoped `repo_data_root` (= `data_root/<repo_slug>`), via new
`HydraFlowConfig` accessors (`repo_data_path()`, `repo_memory_dir`,
`retrospectives_path`, `cost_inferences_path`, `pr_stats_path`; and
`factory_metrics_path` is re-pointed):

| Store | Old (flat) | New (repo-scoped) |
|-------|-----------|-------------------|
| Run artifacts | `data_root/runs/` | `repo_data_root/runs/` |
| Cost inferences | `data_root/metrics/prompt/inferences.jsonl` | `repo_data_root/metrics/prompt/inferences.jsonl` |
| PR telemetry aggregates | `data_root/metrics/prompt/pr_stats.json` | `repo_data_root/metrics/prompt/pr_stats.json` |
| Factory metrics | `data_root/diagnostics/factory_metrics.jsonl` | `repo_data_root/diagnostics/factory_metrics.jsonl` |
| Retrospective insights | `data_root/memory/{retrospectives.jsonl,filed_patterns.json,retrospective_queue.jsonl}` | `repo_data_root/memory/…` |
| Harness insights | `data_root/memory/{harness_failures.jsonl,harness_suggestions.jsonl,harness_proposed.json}` | `repo_data_root/memory/…` |
| Review insights | `data_root/memory/{reviews.jsonl,proposed_categories.json,proposal_metadata.json}` | `repo_data_root/memory/…` |

This splits the `memory/` directory: per-repo **insight** files move to
`repo_data_root/memory/` (via `config.repo_memory_dir`), while cross-repo
**knowledge** files stay flat under `config.memory_dir` (`data_root/memory/`):
`adr_decisions.jsonl`, `hitl_recommendations.jsonl`, `items.jsonl`,
`verification_records.jsonl`.

**One-time migration (host-only).** `data_migration.migrate_flat_operational_stores(config)`
copies any existing flat store into the repo-scoped location, mirroring the
copy-if-target-absent, `shutil.copy2`, log-on-`OSError` mechanism of
`_resolve_repo_scoped_paths`. It is idempotent (skips when the scoped target
exists) and runs **once at host startup** (`server._run`) with the *host* config,
before any member runtime is built. Rationale: under a shared `data_root` the
legacy flat data was written by the host process and is already comingled across
repos, so it belongs to the default/host repo — "the default repo keeps its
history". Member repos start clean and never claim the host's flat data. A no-op
when `repo_data_root == data_root` (no slug to scope under).

**Out of scope (deferred, same mechanism applies later).** These per-repo-ish
stores remain flat for now and are candidates for a follow-up slice:
`metrics/history_cache.json` (host-only — read/written only for the default repo,
no cross-repo collision), `traces/`, `reflections/`, `outcomes.jsonl`,
`item_scores.json`, health-monitor known-pattern / troubleshooting stores. The
ADR-0010 migration of `log_dir`/`plans_dir` (whole-directory scoping) is likewise
unchanged by this amendment.

## Related

- Source memory: [#1624 — HydraFlow persistence architecture and data layout](https://github.com/T-rav/hydra/issues/1624)
- This ADR: [#1633](https://github.com/T-rav/hydra/issues/1633)
- `src/state:StateTracker` — crash-recovery state persistence
- `src/state/_session.py` — session history persistence (`sessions.jsonl`)
- `src/config.py:_resolve_base_paths`, `src/config.py:_resolve_repo_and_identity`, `src/config.py:_resolve_repo_scoped_paths` — data root and path resolution
- `src/data_migration.py:migrate_flat_operational_stores` — one-time host-only migration of flat per-repo stores to `repo_data_root` (Amendment D2)
- `src/config.py:HydraFlowConfig.repo_data_path`, `repo_memory_dir`, `cost_inferences_path`, `retrospectives_path`, `factory_metrics_path` — repo-scoped store accessors (Amendment D2)
- ADR-0007 (Dashboard API Multi-Repo Scoping), ADR-0038 (Multi-Repo Architecture Wiring Pattern) — the shared-`data_root` registry model that motivates Amendment D2
- `src/config.py:load_config_file`, `src/config.py:save_config_file` — config snapshot persistence
- `src/config.py:HydraFlowConfig.data_root` — data root configuration
- `src/metrics_manager.py` — repo-slug namespaced metrics
- `src/file_util.py:atomic_write` — atomic file write helper
- ADR-0003 (Git Worktrees for Issue Isolation) — worktree isolation (complementary filesystem layout)
- ADR-0006 (RepoRuntime Isolation Architecture), superseded by ADR-0009 (Multi-Repo Process-Per-Repo Model) — RepoRuntime isolation (per-repo process boundaries)
- ADR-0009 (Multi-Repo Process-Per-Repo Model) — `_resolve_repo_scoped_paths()` scoping that places state files under `data_root/<repo_slug>/`
- ADR-0010 (Worktree and Path Isolation Architecture) — mandates repo-slug scoping for `log_dir`, `plans_dir`, `memory_dir` to `data_root/<repo_slug>/`
