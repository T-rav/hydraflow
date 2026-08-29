# HydraFlow Standard — Ports and Loops

Every hexagonal port and every background loop in HydraFlow follows a
shared structural contract. This document defines that contract so that
new ports and loops are consistent, testable, and observable from day
one — without requiring a reviewer to catch missing pieces.

## Ports

A **port** is a `@runtime_checkable` `Protocol` in `src/ports.py` that
abstracts an I/O boundary. Adapters implement ports; phases and loops
depend on ports, not adapters.

### Per-port requirements

| Requirement | Where | Detail |
|---|---|---|
| **Protocol definition** | `src/ports.py` | `@runtime_checkable` `Protocol`; pure interface, no state. |
| **Production adapter** | `src/<adapter>.py` | Concrete implementation; wired in the service registry. |
| **Fake adapter** | `src/mockworld/fakes/fake_<name>.py` | `Fake<Name>` class used in MockWorld scenarios and unit tests. Must satisfy the Protocol structurally. |
| **Wiki term entry** | `docs/wiki/terms/<kebab-name>.md` | YAML frontmatter + Definition + Invariants. UL lint must pass. |
| **ADR** | `docs/adr/XXXX-<kebab-name>.md` | Documents the decision to introduce the port and its behavioral contract. |
| **Standard entry** | This document, `§ Per-port registry` | Generated. The row appears once the Protocol exists; run `make arch-regen`. Do not add it by hand. |

### Per-port registry

> **Generated. Do not hand-edit.** Every cell is derived from source by
> `src/arch/generators/ports_and_loops_standard.py`: the port and its fake from
> the extractors, the ADR column from a scan of `docs/adr/`, the term column
> from each term file's own `name:` frontmatter. Run `make arch-regen` to
> refresh; `make arch-check` fails on drift. A `—` is a real gap in the
> contract above, not a formatting placeholder — filling it means writing the
> ADR or the term entry, not editing this row.

<!-- generated:port-registry -->
| Port | Module | Fake | ADR | Wiki term |
|---|---|---|---|---|
| `AgentPort` | `src/ports.py` | `FakeAgent` | 0066 | [agent-port.md](../../wiki/terms/agent-port.md) |
| `BotPRPort` | `src/term_proposer_loop.py` | `FakeBotPR` | 0068 | [bot-pr-port.md](../../wiki/terms/bot-pr-port.md) |
| `ConformanceRunnerPort` | `src/ports.py` | `FakeConformanceRunner` | — | — |
| `IssueFetcherPort` | `src/ports.py` | `FakeIssueFetcher` | 0067, 0081 | [issue-fetcher-port.md](../../wiki/terms/issue-fetcher-port.md) |
| `IssueStorePort` | `src/ports.py` | `FakeIssueStore` | 0041 | [issue-store-port.md](../../wiki/terms/issue-store-port.md) |
| `ObservabilityPort` | `src/ports.py` | `FakeObservability` | 0072 | [observability-port.md](../../wiki/terms/observability-port.md) |
| `PRPort` | `src/ports.py` | `FakePR` | 0002, 0045, 0052, 0056, 0068, 0069, 0075, 0077, 0109, 0115 | [pr-port.md](../../wiki/terms/pr-port.md) |
| `ReviewInsightStorePort` | `src/ports.py` | `FakeReviewInsightStore` | 0070 | [review-insight-store-port.md](../../wiki/terms/review-insight-store-port.md) |
| `RouteBackCounterPort` | `src/route_back.py` | `FakeRouteBackCounter` | 0071 | [route-back-counter-port.md](../../wiki/terms/route-back-counter-port.md) |
| `WorkspacePort` | `src/ports.py` | `FakeWorkspace` | 0003, 0050, 0069, 0112, 0137 | [workspace-port.md](../../wiki/terms/workspace-port.md) |
<!-- /generated:port-registry -->

## Loops

A **loop** is a `BaseBackgroundLoop` subclass that runs on a fixed interval
inside the factory. Loops are the dark factory's autonomous workers —
each is responsible for one caretaking concern.

### Per-loop requirements

| Requirement | Where | Detail |
|---|---|---|
| **Kill-switch** | `_do_work` method | First check: `if not self._enabled_cb(self._worker_name): return {"status": "disabled"}`. ADR-0049 mandates this on every loop. |
| **Config gate** | `_do_work` method | Second check: `if not self._config.<loop>_loop_enabled: return {"status": "config_disabled"}` for static-config-gated loops. |
| **Unit tests** | `tests/test_<loop>.py` | Full coverage including kill-switch path. |
| **MockWorld scenario** | `tests/scenarios/test_<loop>_scenario.py` | Pattern A (catalog) or Pattern B (direct) — see `docs/standards/testing/`. |
| **Wiki term entry** | `docs/wiki/terms/<kebab-loop>.md` | YAML frontmatter + Definition + Invariants. |
| **ADR** | `docs/adr/XXXX-<kebab-loop>.md` | Documents the decision to introduce the loop. |
| **Standard entry** | This document, `§ Per-loop registry` | Generated. The row appears once the loop class exists; run `make arch-regen`. Do not add it by hand. |

### Per-loop registry

> **Generated. Do not hand-edit.** Same derivation as the port registry
> above (`src/arch/generators/ports_and_loops_standard.py`). The tick column
> is the interval the loop declares; a `—` there means the extractor could not
> find one, which for a `BaseBackgroundLoop` subclass is worth a look.
>
> This table is the standard's inventory — one row per live loop, and the
> `—` cells are the contract's open gaps. Coverage detail (unit, scenario,
> sandbox) lives in `docs/arch/generated/coverage_matrix.md`; the navigable
> ADR cross-reference lives in `docs/arch/generated/adr_xref.md`.

<!-- generated:loop-registry -->
| Loop | Module | Tick (s) | ADR | Wiki term |
|---|---|---|---|---|
| `ADRReviewerLoop` | `src/adr_reviewer_loop.py` | 86400 | 0079 | [adr-reviewer-loop.md](../../wiki/terms/adr-reviewer-loop.md) |
| `AdrConformanceLoop` | `src/adr_conformance_loop.py` | 86400 | 0100, 0104, 0136 | — |
| `AutoAgentPreflightLoop` | `src/auto_agent_preflight_loop.py` | 120 | 0050, 0063, 0084 | — |
| `AutoTightenLoop` | `src/auto_tighten_loop.py` | 86400 | 0104 | — |
| `BranchProtectionAuditorLoop` | `src/branch_protection_auditor_loop.py` | 604800 | 0082 | — |
| `CIMonitorLoop` | `src/ci_monitor_loop.py` | 300 | 0029, 0065 | [ci-monitor-loop.md](../../wiki/terms/ci-monitor-loop.md) |
| `ContractRefreshLoop` | `src/contract_refresh_loop.py` | 604800 | 0045, 0047 | [contract-refresh-loop.md](../../wiki/terms/contract-refresh-loop.md) |
| `ConvergenceOscillationLoop` | `src/convergence_oscillation_loop.py` | 3600 | 0096, 0097, 0098 | — |
| `CorpusLearningLoop` | `src/corpus_learning_loop.py` | 3600 | 0045 | [corpus-learning-loop.md](../../wiki/terms/corpus-learning-loop.md) |
| `CostBudgetWatcherLoop` | `src/cost_budget_watcher_loop.py` | 300 | 0054, 0120 | — |
| `DependabotMergeLoop` | `src/dependabot_merge_loop.py` | 3600 | 0054, 0057, 0058 | [dependabot-merge-loop.md](../../wiki/terms/dependabot-merge-loop.md) |
| `DetectorCalibrationLoop` | `src/detector_calibration_loop.py` | 86400 | — | — |
| `DiagnosticLoop` | `src/diagnostic_loop.py` | 30 | 0050 | [diagnostic-loop.md](../../wiki/terms/diagnostic-loop.md) |
| `DiagramLoop` | `src/diagram_loop.py` | 14400 | 0001, 0093 | [diagram-loop.md](../../wiki/terms/diagram-loop.md) |
| `DisturbanceDampenerLoop` | `src/disturbance_dampener_loop.py` | — | 0101, 0120 | [disturbance-dampener-loop.md](../../wiki/terms/disturbance-dampener-loop.md) |
| `EdgeProposerLoop` | `src/edge_proposer_loop.py` | 86400 | 0058, 0060, 0062, 0126 | [edge-proposer-loop.md](../../wiki/terms/edge-proposer-loop.md) |
| `EntryEvidenceLoop` | `src/entry_evidence_loop.py` | 86400 | 0062, 0078, 0126 | [entry-evidence-loop.md](../../wiki/terms/entry-evidence-loop.md) |
| `EpicMonitorLoop` | `src/epic_monitor_loop.py` | 1800 | 0080, 0081, 0091 | — |
| `EpicSweeperLoop` | `src/epic_sweeper_loop.py` | 3600 | 0080, 0081, 0091, 0105 | — |
| `ErosionMetricsLoop` | `src/erosion_metrics_loop.py` | 86400 | 0120, 0122, 0126 | — |
| `EscapeLedgerLoop` | `src/escape_ledger_loop.py` | 14400 | 0115 | — |
| `FailOpenMonitorLoop` | `src/fail_open_monitor_loop.py` | 14400 | 0120 | — |
| `FakeCoverageAuditorLoop` | `src/fake_coverage_auditor_loop.py` | 604800 | 0045, 0047, 0056, 0089 | [fake-coverage-auditor-loop.md](../../wiki/terms/fake-coverage-auditor-loop.md) |
| `FitnessScorecardLoop` | `src/fitness_scorecard_loop.py` | 86400 | 0093, 0100, 0104 | [fitness-scorecard-loop.md](../../wiki/terms/fitness-scorecard-loop.md) |
| `FlakeTrackerLoop` | `src/flake_tracker_loop.py` | 14400 | 0045, 0056, 0065, 0089, 0099, 0120 | [flake-tracker-loop.md](../../wiki/terms/flake-tracker-loop.md) |
| `GateActivatorLoop` | `src/gate_activator_loop.py` | 604800 | 0082 | — |
| `GateHealthLoop` | `src/gate_health_loop.py` | 604800 | 0120 | — |
| `GatewayCoverageLoop` | `src/gateway_coverage_loop.py` | 3600 | 0110 | — |
| `GitHubCacheLoop` | `src/github_cache_loop.py` | 300 | 0076 | [git-hub-cache-loop.md](../../wiki/terms/git-hub-cache-loop.md) |
| `GoalSupervisorLoop` | `src/goal_supervisor_loop.py` | 600 | 0124 | [goal-supervisor-loop.md](../../wiki/terms/goal-supervisor-loop.md) |
| `HealthMonitorLoop` | `src/health_monitor_loop/_loop.py` | 600 | 0045, 0046, 0093, 0106, 0124 | — |
| `HumanSteeringLoop` | `src/human_steering_loop.py` | — | 0103 | [human-steering-loop.md](../../wiki/terms/human-steering-loop.md) |
| `InterventionTallyLoop` | `src/intervention_tally_loop.py` | 86400 | — | — |
| `IssueRefinementLoop` | `src/issue_refinement_loop.py` | 86400 | — | — |
| `LabelDriftWatcherLoop` | `src/label_drift_watcher_loop.py` | 600 | 0088 | — |
| `LiveCorpusReplayLoop` | `src/live_corpus_replay_loop.py` | 900 | 0086 | [live-corpus-replay-loop.md](../../wiki/terms/live-corpus-replay-loop.md) |
| `LogIngestLoop` | `src/log_ingest_loop.py` | 14400 | — | — |
| `MemoryBacklogLoop` | `src/memory_backlog_loop.py` | 86400 | 0089, 0120 | — |
| `MergeStateWatcherLoop` | `src/merge_state_watcher_loop.py` | 600 | 0075, 0077 | [merge-state-watcher-loop.md](../../wiki/terms/merge-state-watcher-loop.md) |
| `PRUnstickerLoop` | `src/pr_unsticker_loop.py` | 3600 | 0075, 0077 | [pr-unsticker-loop.md](../../wiki/terms/pr-unsticker-loop.md) |
| `PrRedRepairLoop` | `src/pr_red_repair_loop.py` | 300 | — | — |
| `PricingRefreshLoop` | `src/pricing_refresh_loop.py` | 86400 | 0078, 0093 | [pricing-refresh-loop.md](../../wiki/terms/pricing-refresh-loop.md) |
| `PrinciplesAuditLoop` | `src/principles_audit_loop.py` | 604800 | 0045, 0056, 0120 | — |
| `RCBudgetLoop` | `src/rc_budget_loop.py` | 14400 | 0045, 0120 | [rc-budget-loop.md](../../wiki/terms/rc-budget-loop.md) |
| `RailsDriftCaretakerLoop` | `src/rails_drift_caretaker_loop.py` | 86400 | 0121 | [rails-drift-caretaker-loop.md](../../wiki/terms/rails-drift-caretaker-loop.md) |
| `RepoWikiLoop` | `src/repo_wiki_loop.py` | 3600 | 0032, 0053, 0061, 0062, 0064 | — |
| `ReportIssueLoop` | `src/report_issue_loop.py` | 30 | 0013, 0018, 0028, 0045, 0120 | [report-issue-loop.md](../../wiki/terms/report-issue-loop.md) |
| `RetrospectiveLoop` | `src/retrospective_loop.py` | 86400 | 0074, 0093, 0120 | — |
| `RunsGCLoop` | `src/runs_gc_loop.py` | 3600 | 0073 | — |
| `SampledAuditLoop` | `src/sampled_audit_loop.py` | 14400 | 0115, 0120 | — |
| `SandboxFailureFixerLoop` | `src/sandbox_failure_fixer_loop.py` | 3600 | 0052, 0063, 0097, 0101 | — |
| `SecondOrderVitalsLoop` | `src/second_order_vitals_loop.py` | 86400 | 0120 | — |
| `SecurityPatchLoop` | `src/security_patch_loop.py` | 3600 | 0029, 0065 | — |
| `SkillPromptEvalLoop` | `src/skill_prompt_eval_loop.py` | 604800 | 0045 | [skill-prompt-eval-loop.md](../../wiki/terms/skill-prompt-eval-loop.md) |
| `StagingBisectLoop` | `src/staging_bisect_loop.py` | 600 | 0045, 0048, 0063 | — |
| `StagingPromotionLoop` | `src/staging_promotion_loop.py` | 300 | 0042, 0108 | — |
| `StaleIssueGCLoop` | `src/stale_issue_gc_loop.py` | 3600 | 0029, 0072 | [stale-issue-gc-loop.md](../../wiki/terms/stale-issue-gc-loop.md) |
| `StaleIssueLoop` | `src/stale_issue_loop.py` | 86400 | 0072 | — |
| `TermProposerLoop` | `src/term_proposer_loop.py` | 14400 | 0054, 0057, 0060, 0061, 0062, 0068, 0126 | — |
| `TermPrunerLoop` | `src/term_pruner_loop.py` | 86400 | 0057, 0060, 0062, 0068 | [term-pruner-loop.md](../../wiki/terms/term-pruner-loop.md) |
| `TriageRetryLoop` | `src/triage_retry_loop.py` | 900 | 0063 | — |
| `TrustFleetSanityLoop` | `src/trust_fleet_sanity_loop.py` | 600 | 0045, 0046, 0093 | — |
| `WikiRotDetectorLoop` | `src/wiki_rot_detector_loop.py` | 604800 | 0045, 0056, 0089, 0099, 0120, 0126 | [wiki-rot-detector-loop.md](../../wiki/terms/wiki-rot-detector-loop.md) |
| `WorkspaceGCLoop` | `src/workspace_gc_loop.py` | 1800 | 0069, 0093 | [workspace-gc-loop.md](../../wiki/terms/workspace-gc-loop.md) |
<!-- /generated:loop-registry -->

## Discoverability

This standard is referenced from:

- `docs/standards/factory_operation/README.md` — kernel standards table
- `docs/wiki/gotchas.md` — "Background loop wiring: synchronize 5 locations"
- `docs/arch/generated/coverage_matrix.md` — Standard column for each loop and port

## Enforced by

The gates that hold this document to its artifact. This list is the same
set as `enforced_by` in [`standard.yaml`](standard.yaml); editing either
side alone reddens `tests/architecture/test_standards_registry.py`, which
also checks that every cited path is still **collected by pytest** — a
gate that exists but never runs is a citation to nothing.

<!-- standard:enforced-by -->
- `tests/architecture/test_ports_and_loops_standard_drift.py`
<!-- /standard:enforced-by -->
