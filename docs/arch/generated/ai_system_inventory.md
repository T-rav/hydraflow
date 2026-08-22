# AI System Inventory

**Generated — do not edit.** Derived by `arch.runner` from
`src/orchestrator.py` (`bg_loop_registry`), `src/service_registry.py`
annotations, `src/dashboard_routes/_control_routes.py` (`_bg_worker_defs`),
`docs/arch/functional_areas.yml`, `src/config.py` role fields, and the
worker source modules. Every input is a file in the checkout, so the body
is byte-stable for drift CI.

This is the model-inventory view of the factory (SR 11-7 / EU-AI-Act-style
technical documentation): every autonomous decision-maker, the config
model role(s) it resolves, its watchdog class, and its human-oversight
points.

## Conventions

- **Kill-switch (ADR-0049):** every background loop gates its tick on the
  in-body enabled check (`if not self._enabled_cb(...)`), toggled live
  from the dashboard System tab and persisted in state. Enforced fleetwide
  by `tests/test_loop_kill_switch_completeness.py`, so it is stated once
  here rather than repeated per row.
- **Human oversight baseline:** all workers are kill-switchable and
  telemetered on the dashboard; loop-authored changes land as PRs behind
  branch protection. The *Oversight* column lists the additional signals
  detected in the worker's own source: `HITL escalation` (routes work to
  the human-in-the-loop label queue) and `PR review + merge gate` (output
  ships as a pull request).
- **Model role detection:** config `*_model` fields referenced in the
  worker's source module and its direct (one-hop) src-local imports; the
  implementation role (the bare `model` field) is matched as a
  `config.model` attribute read. `src/config.py` and
  `src/service_registry.py` are excluded from scan scope. `—` means no
  direct LLM role was detected (mechanical caretaker).
- **Long LLM cycle:** loops that set `LONG_LLM_CYCLE = True` earn the
  longer per-cycle watchdog bound (`loop_watchdog_llm_seconds`).

## Model roles

Role registry from `config._ENV_COMBO_OVERRIDES` — each combo env var resolves a `(tool, model)` pair after the SYSTEM/BACKGROUND cascade (#9717 resolution).

| Env combo | Tool field | Model field |
|---|---|---|
| `HYDRAFLOW_SYSTEM` | `system_tool` | `system_model` |
| `HYDRAFLOW_BACKGROUND` | `background_tool` | `background_model` |
| `HYDRAFLOW_IMPLEMENT` | `implementation_tool` | `model` |
| `HYDRAFLOW_REVIEW` | `review_tool` | `review_model` |
| `HYDRAFLOW_TEST_ADEQUACY_VERIFIER` | `test_adequacy_verifier_tool` | `test_adequacy_verifier_model` |
| `HYDRAFLOW_PLANNER` | `planner_tool` | `planner_model` |
| `HYDRAFLOW_TRIAGE` | `triage_tool` | `triage_model` |
| `HYDRAFLOW_AC` | `ac_tool` | `ac_model` |
| `HYDRAFLOW_TRANSCRIPT_SUMMARY` | `transcript_summary_tool` | `transcript_summary_model` |
| `HYDRAFLOW_WIKI_COMPILATION` | `wiki_compilation_tool` | `wiki_compilation_model` |
| `HYDRAFLOW_ADR_REVIEW` | `adr_review_tool` | `adr_review_model` |
| `HYDRAFLOW_REPORT_ISSUE` | `report_issue_tool` | `report_issue_model` |
| `HYDRAFLOW_TERM_PROPOSER` | `term_proposer_tool` | `term_proposer_model` |

## Background loops (64)

| Worker | Loop class | Area | Model role(s) | Long LLM cycle | Oversight | Purpose |
|---|---|---|---|---|---|---|
| `adr_conformance` | `AdrConformanceLoop` | Governance & Audit | — | — | HITL escalation | Evaluates every Accepted ADR's `Enforced by:` checks and files/updates remediation issues on drift. See ADR-0100. |
| `adr_reviewer` | `ADRReviewerLoop` | Intake | `adr_review_model` | — | — | Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate. |
| `auto_agent_preflight` | `AutoAgentPreflightLoop` | Autonomy | `adr_review_model`, `model` | — | HITL escalation | Intercepts hitl-escalation issues; runs an emulated-engineer subprocess to attempt autonomous resolution before the issue surfaces to a human (spec §1–§11; ADR-0050). |
| `auto_tighten` | `AutoTightenLoop` | Repo Health | — | — | — | Locks in coverage-floor gains |
| `branch_protection_auditor` | `BranchProtectionAuditorLoop` | Governance & Audit | — | — | — | Audits live GitHub branch protection against the canonical rulesets generated from gates.toml; files an issue on drift. See ADR-0082. |
| `ci_monitor` | `CIMonitorLoop` | Repo Health | — | — | — | Detects failing CI on main and files/auto-closes issues. |
| `contract_refresh` | `ContractRefreshLoop` | Governance & Audit | — | — | HITL escalation; PR review + merge gate | Re-records fake-adapter cassettes and opens refresh PRs when committed cassettes drift from live behavior. |
| `convergence_oscillation` | `ConvergenceOscillationLoop` | Autonomy | — | — | HITL escalation | Scans issue convergence ledgers for cross-boundary oscillation (repeated LOOP_BACK across triage/shape/plan or recurring review-lap findings) and escalates stuck issues to HITL, once each. See ADR-0098. |
| `corpus_learning` | `CorpusLearningLoop` | Learning & Insights | `corpus_learning_synthesis_model`, `review_model`, `test_adequacy_verifier_model` | — | HITL escalation; PR review + merge gate | Synthesizes adversarial cases from skill/discover/shape escape signals and opens corpus-update PRs. |
| `cost_budget_watcher` | `CostBudgetWatcherLoop` | Operations | — | — | — | Polls rolling-24h LLM spend; disables caretaker loops when daily cap exceeded. Default unlimited. |
| `dependabot_merge` | `DependabotMergeLoop` | Repo Health | — | — | HITL escalation | Auto-merges dependency update PRs from configured bots after CI passes. |
| `detector_calibration` | `DetectorCalibrationLoop` | Autonomy | — | — | HITL escalation | Mines closed escalations for repeat-offender subjects — churn means the detector is miscalibrated, not the code. |
| `diagnostic` | `DiagnosticLoop` | Operations | `model` | ✅ | HITL escalation | Analyzes escalated issues, classifies severity, and attempts targeted fixes before HITL. |
| `diagram_loop` | `DiagramLoop` | Governance & Audit | — | — | PR review + merge gate | Self-documenting architecture caretaker. Walks src/, tests/, docs/adr/ every 4h; emits regenerated docs/arch/generated/ markdown + opens a PR when the live truth has drifted. Per ADR-0029 (caretaker pattern) and the Architecture Knowledge System spec. |
| `disturbance_dampener` | `DisturbanceDampenerLoop` | Autonomy | — | ✅ | PR review + merge gate | Burns down disturbance backlog by selecting units per dimension+file, dispatching an auto-agent fix, and opening one PR per file (ADR-0095). |
| `edge_proposer` | `EdgeProposerLoop` | Learning & Insights | — | — | — | Caretaker that proposes depends_on + implements edges between existing UL terms based on import graph + class inheritance. See ADR-0058. |
| `entry_evidence` | `EntryEvidenceLoop` | Learning & Insights | — | — | — | Caretaker that links wiki entries to UL terms via LLM matching, populating Term.evidence so the Atlas Domain view can render entry leaves under their term parents. See ADR-0062. |
| `epic_monitor` | `EpicMonitorLoop` | Operations | — | — | — | Detects stale epics and refreshes progress cache so the dashboard shows accurate sub-issue rollups. |
| `epic_sweeper` | `EpicSweeperLoop` | Operations | — | — | — | Periodically sweeps open epics and auto-closes those with all sub-issues resolved. |
| `erosion_metrics` | `ErosionMetricsLoop` | Repo Health | — | — | — | v1: runs the change-spread and concept-scatter sensors over commits merged since the last tick; files above-baseline drift as hydraflow-find issues for human triage (Pattern B). See #10107, epic #10104. |
| `escape_ledger` | `EscapeLedgerLoop` | Repo Health | — | — | HITL escalation | Falsification instrument (read-only, Pattern B): records post-merge escapes (revert/hotfix/regression-pin/bug-issue) to an append-only ledger with mechanical attribution, and renders escapes-per-100-merges + month-over-month erosion trend surfaces. Never gates or fixes. See #10367. |
| `fail_open_monitor` | `FailOpenMonitorLoop` | Repo Health | `background_model`, `judge_independent_model`, `review_model` | — | — | Watches the judge fail-open ledger; applies a Shewhart control limit to the daily fail-open rate and files a hydraflow-find above-limit (Pattern B). Part of the judge-independence budget + fail-visible dispatch (#10371). |
| `fake_coverage_auditor` | `FakeCoverageAuditorLoop` | Learning & Insights | — | — | HITL escalation | Flags fake-adapter methods without cassettes and scenario helpers nobody calls. |
| `fitness_scorecard` | `FitnessScorecardLoop` | Governance & Audit | — | — | — | Computes per-loop fitness scores each tick by combining event history and issue attribution. Persists to fitness.jsonl and regenerates docs/arch/generated/loop-fitness.md. Read-only caretaker per ADR-0029. |
| `flake_tracker` | `FlakeTrackerLoop` | Repo Health | — | — | HITL escalation | Detects persistently flaky tests across recent RC runs and files flake-tracker issues. |
| `gate_activator` | `GateActivatorLoop` | Governance & Audit | — | — | — | Proposes activating planned gates in gates.toml once the surface each protects exists (producing job + make target present, profile matches); files a reviewed issue. See ADR-0082. |
| `gate_health` | `GateHealthLoop` | Repo Health | — | — | — | Weekly read-only CI-gate auditor: pass-rate distributions, blame-correlation, missing failure artifacts, stale quarantines. |
| `gateway_coverage` | `GatewayCoverageLoop` | Meta-Observability | — | — | — | Measures the share of LLM spend transiting the gateway. |
| `github_cache` | `GitHubCacheLoop` | Operations | — | — | HITL escalation | Single-poller cache for GitHub data; serves all dashboard + loop consumers from one shared snapshot to avoid rate-limit fan-out. |
| `goal_supervisor` | `GoalSupervisorLoop` | Meta-Observability | `credit_failover_model`, `goal_supervisor_model`, `model` | ✅ | — | Tier-2 liveness supervisor: reads the read-only factory health snapshot, hands it to a Fable agent under the standing goal 'keep the factory alive & healthy', and nudges the reversible / escalates the rest. Default OFF. See ADR-0124. |
| `health_monitor` | `HealthMonitorLoop` | Meta-Observability | — | — | HITL escalation | Analyzes pipeline trends, auto-tunes parameters, detects knowledge gaps, and ingests log patterns. |
| `human_steering` | `HumanSteeringLoop` | Autonomy | — | — | — | Senses per-issue GitHub-comment steering directives (/steer, /pause, /resume, /redo, /abort) each tick and writes the steering reference (ADR-0099 #4). |
| `intervention_tally` | `InterventionTallyLoop` | Repo Health | `background_model`, `intervention_tally_model`, `maintenance_model` | ✅ | HITL escalation | Attention-side telemetry (read-only, Pattern B): senses human touches (steering/HITL/control-route/CLI), classifies them into a fixed taxonomy (mechanical + bounded cheap-LLM for free-text), and renders interventions-per-100-merges (same denominator as the escape ledger), the per-loop trust table, and loops-per-governor. Never gates or fixes. See #10369. |
| `issue_refinement` | `IssueRefinementLoop` | Repo Health | `background_model`, `issue_refinement_model`, `maintenance_model` | ✅ | — | Backlog-wide duplicate detection, priority scoring, and a rolling operator digest issue. |
| `label_drift_watcher` | `LabelDriftWatcherLoop` | Repo Health | — | — | HITL escalation | Periodic scan for cross-entity issue/PR label drift (e.g., issue at hydraflow-ready while linked PR at hydraflow-review with commits); reconciles via per-entity swap_pipeline_labels. See ADR-0088. |
| `live_corpus_replay` | `LiveCorpusReplayLoop` | Governance & Audit | — | — | HITL escalation | Diffs fresh shadow-corpus samples against fake-adapter outputs to catch value-level drift between real and fake adapters; files one hydraflow-find issue per unique drift signature. See #8786 / ADR-0045. |
| `log_ingest` | `LogIngestLoop` | Intake | — | — | — | Clusters and dedups recurring errors/warnings in HydraFlow's own server log and files them as fix-issues for the pipeline. |
| `memory_backlog` | `MemoryBacklogLoop` | Learning & Insights | — | — | HITL escalation | Files hydraflow-find issues for pending entries in docs/wiki/memory-feedback/. |
| `merge_state_watcher` | `MergeStateWatcherLoop` | Operations | — | — | HITL escalation | Auto-rebases or HITL-escalates open PRs flagged mergeable=CONFLICTING (RC, dependabot, agent). |
| `pr_red_repair` | `PrRedRepairLoop` | Repo Health | `model` | — | HITL escalation | Detects settled-red open PRs and bounded-reruns infra-flake CI; escalates via rollup issue once the rerun budget is exhausted (#10027 Phase 1). |
| `pr_unsticker` | `PRUnstickerLoop` | Operations | `background_model` | — | HITL escalation | Requeues stalled HITL PRs by validating requirements and reopening flow. |
| `pricing_refresh` | `PricingRefreshLoop` | Learning & Insights | — | — | PR review + merge gate | Daily upstream-pricing refresh caretaker — fetches LiteLLM JSON, opens PR on drift; bounds-guarded, always human-reviewed. |
| `principles_audit` | `PrinciplesAuditLoop` | Governance & Audit | — | — | HITL escalation | Weekly ADR-0044 audit of HydraFlow-self plus managed repos; blocks onboarding on P1–P5 fails. |
| `rails_drift_caretaker` | `RailsDriftCaretakerLoop` | Governance & Audit | — | — | — | Audits each managed repo's live state against its rails.yaml manifest (declared template layers / coverage floor / domain gate scripts) and files deduped drift issues. See ADR-0121. |
| `rc_budget` | `RCBudgetLoop` | Repo Health | — | — | HITL escalation | Detects RC wall-clock bloat via rolling-median + spike signals across recent runs. |
| `repo_wiki` | `RepoWikiLoop` | Learning & Insights | `wiki_compilation_model` | — | HITL escalation; PR review + merge gate | Lints and maintains per-repo knowledge wikis compiled from plan/implement/review cycles. |
| `report_issue` | `ReportIssueLoop` | Intake | `report_issue_model` | ✅ | HITL escalation | Processes queued bug reports into GitHub issues via the configured agent. |
| `retrospective` | `RetrospectiveLoop` | Learning & Insights | — | — | HITL escalation | Captures post-merge outcomes and identifies recurring delivery patterns. |
| `runs_gc` | `RunsGCLoop` | Repo Health | — | — | — | Purges expired pipeline run artifacts per TTL and size-cap config; keeps the runs store from growing unbounded. |
| `sampled_audit` | `SampledAuditLoop` | Repo Health | `background_model`, `maintenance_model`, `sampled_audit_model` | ✅ | — | The silent-escape estimator (read-only, Pattern B): re-audits a governed random sample of merged PRs with a fresh adversarial context, records agree/disagree to audit_samples.jsonl, and renders the disagreement rate + confidence interval as a statistical bound on undetected escapes. Upheld disagreements cross-link into the escape ledger. Never gates, reverts, or fixes. See #10370. |
| `sandbox_failure_fixer` | `SandboxFailureFixerLoop` | Autonomy | `model` | — | HITL escalation | Auto-fixes promotion PRs failing sandbox CI by dispatching the auto-agent |
| `second_order_vitals` | `SecondOrderVitalsLoop` | Repo Health | — | — | HITL escalation | The capstone residual monitor (read-only, Pattern B): reads the four instrument ledgers, gives each of five families its own Shewhart control limit, and computes the green-while-dying verdict (green/watch/diverging) — adverse drift across ≥3 families sustained over 2 windows while primary health is green. `diverging` files ONE never-batched find + HITL per episode; `watch` is a dashboard state change only. Never gates or fixes. See #10373. |
| `security_patch` | `SecurityPatchLoop` | Repo Health | — | — | — | Polls Dependabot alerts and files issues for fixable vulnerabilities. |
| `skill_prompt_eval` | `SkillPromptEvalLoop` | Learning & Insights | `background_model`, `maintenance_model`, `skill_prompt_refine_model` | — | HITL escalation; PR review + merge gate | Weekly adversarial-corpus gate against built-in skills; flags PASS→FAIL regressions. |
| `staging_bisect` | `StagingBisectLoop` | Release | — | — | HITL escalation; PR review + merge gate | Bisects RC red between last-green and current-red; opens auto-revert PRs and watches the next RC. |
| `staging_promotion` | `StagingPromotionLoop` | Release | `ac_model`, `adr_review_model`, `background_model`, `corpus_learning_synthesis_model`, `debug_model`, `planner_model`, `report_issue_model`, `review_model`, `subskill_model`, `system_model`, `transcript_summary_model`, `triage_model`, `wiki_compilation_model` | — | HITL escalation; PR review + merge gate | Cuts release-candidate snapshots from staging and auto-promotes them to main on green CI. See ADR-0042. |
| `stale_issue` | `StaleIssueLoop` | Repo Health | — | — | HITL escalation | Auto-closes stale general issues (excludes HydraFlow lifecycle labels). Per-tag thresholds, configurable. Distinct from Stale Issue GC, which handles HITL escalations. |
| `stale_issue_gc` | `StaleIssueGCLoop` | Repo Health | — | — | HITL escalation | Auto-closes stale HITL escalation issues — posts a farewell comment, capped at 10/cycle. Distinct from Stale General Issue Cleanup, which excludes HF lifecycle labels. |
| `term_proposer` | `TermProposerLoop` | Learning & Insights | — | — | HITL escalation | Caretaker that grows the ubiquitous-language glossary by detecting load-bearing classes without terms (S1+S2+S5 signals), drafting them via LLM, and opening auto-merging bot PRs as `confidence: proposed`. See ADR-0054. |
| `term_pruner` | `TermPrunerLoop` | Learning & Insights | — | — | — | Caretaker that deprecates UL terms whose code_anchor no longer resolves in src/. Companion to TermProposerLoop. See ADR-0057. |
| `triage_retry` | `TriageRetryLoop` | Autonomy | — | — | HITL escalation | Re-runs parked-issue triage every 24h with the original parking reason as context. Caps at 3 retries before escalating to HITL with the triage-retry-exhausted sub-label. Closes the only factory phase with no autonomous re-entry path. See ADR-0063 W2. |
| `trust_fleet_sanity` | `TrustFleetSanityLoop` | Meta-Observability | — | — | HITL escalation | Meta-observer — watches the 9 trust loops for stalls, escalation spam, dedup growth, errors, cost spikes. |
| `wiki_rot_detector` | `WikiRotDetectorLoop` | Governance & Audit | — | — | HITL escalation | Scans per-repo wikis for citations whose source code has moved or vanished. |
| `workspace_gc` | `WorkspaceGCLoop` | Repo Health | — | — | HITL escalation | Garbage-collects stale workspaces and orphaned branches. |

## Pipeline workers (6)

Dashboard workers that are not background loops: the label-routed pipeline phases (ADR-0002) plus orchestrator-internal helpers. Phases escalate to the HITL label queue on attempt exhaustion and their output merges only through the PR review + merge gates.

| Worker | Model role(s) | Oversight | Purpose |
|---|---|---|---|
| `implement` | `credit_failover_model`, `model`, `planner_model`, `review_model`, `test_adequacy_verifier_model`, `transcript_summary_model` | HITL escalation; PR review + merge gate | Runs coding agents to implement planned issues and open pull requests. |
| `pipeline_poller` | — | — | Refreshes live pipeline snapshots for dashboard queue/status rendering. |
| `plan` | `planner_model`, `transcript_summary_model`, `wiki_compilation_model` | HITL escalation | Builds implementation plans for triaged issues that are ready to execute. |
| `review` | `review_model`, `transcript_summary_model`, `wiki_compilation_model` | HITL escalation | Reviews PRs, applies fixes, and merges approved work when checks pass. |
| `review_insights` | — | HITL escalation | Aggregates recurring review feedback into improvement opportunities. |
| `triage` | `planner_model`, `triage_model` | HITL escalation | Classifies freshly discovered issues and routes them into the pipeline. |

<!-- arch:generated -->
