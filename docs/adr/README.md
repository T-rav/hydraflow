# Architecture Decision Records

Lightweight ADRs documenting key design decisions in HydraFlow.

## Format

Each ADR has: **Status**, **Date**, **Enforcement**, **Enforced by** (when
required), **Context**, **Decision**, **Consequences**, and optionally
**Alternatives considered** and **Related** links. A **control-plane** ADR also
carries a lineage line (**Precedent** and/or **Divergence** — see below).

When referencing source code anywhere in an ADR (Related, Context, Decision,
Consequences), use `module:function_or_class` format (e.g. `src/config.py:HydraFlowConfig`).
**Omit line numbers** — they drift as code evolves and become stale quickly.

### Lineage — Precedent and Divergence (optional)

Two optional, single-line header fields (see
[ADR-0113](0113-adr-lineage-precedent-and-divergence.md)) let a control-plane
ADR — a decision that defines the control system — separate *inherited*
engineering from *genuine* divergence:

- `**Precedent:** <tradition> (<canonical source>)` — the named engineering
  tradition this decision inherits. Must be a **real, citable** tradition;
  retrofitted branding fails review.
- `**Divergence:** <assumption>, <forcing condition>, <rule> (<receipt>)` — the
  assumption in that tradition that breaks here, **citing the receipt** (an
  ADR, incident, or audit finding) that forced it. A `Divergence:` without a
  receipt is not accepted.

Write each as its own line (not a bullet); both the bold-inline and plain
forms parse. The working heuristic: unforced invention is a defect; forced
invention has a named forcing condition and a receipt. The `P1.17` audit check
(advisory today, escalating to blocking once the seed pass lands) warns when a
control-plane ADR carries neither line and flags any receipt-less `Divergence:`.

### Enforcement

Every ADR with **Status: Accepted** (outside a shrinking grandfather list)
MUST declare an `**Enforcement:**` kind — see [ADR-0100](0100-adr-conformance-as-a-measured-contract.md).
Value is one of:

- `enforced` — asserts a runnable invariant. Requires an `**Enforced by:**`
  line naming typed-prefix checks (`pytest:tests/test_x.py`,
  `make:some-target`) that must resolve (the file/function/target must exist)
  and be side-effect-free.
- `manual` — a real guardrail that is human-verified rather than
  machine-run. Requires an `**Enforced by:**` process pointer.
- `decision-of-record` — a choice with no runtime predicate to check (no
  `**Enforced by:**` required).

`tests/test_adr_conformance_coverage.py` is the CI-blocking coverage ratchet:
it validates every non-grandfathered Accepted ADR declares a recognized
`**Enforcement:**` value, that `enforced` checks resolve to a real
pytest node or Makefile target and aren't on the mutating-target denylist,
and that the grandfather list only shrinks. `AdrConformanceLoop` is the
post-merge companion that actually executes `enforced` checks on a slow
cadence and files remediation issues on drift.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-five-concurrent-async-loops.md) | Five Concurrent Async Loops | Accepted |
| [0002](0002-labels-as-state-machine.md) | GitHub Labels as the Pipeline State Machine | Accepted |
| [0003](0003-git-worktrees-for-isolation.md) | Git Worktrees for Issue Isolation | Superseded |
| [0004](0004-agent-cli-as-runtime.md) | CLI-based Agent Runtime (Claude / Codex / Pi.dev) | Accepted |
| [0005](0005-pr-recovery-and-zero-diff-branch-handling.md) | PR Recovery and Zero-Diff Branch Handling in Implement Phase | Accepted |
| [0006](0006-repo-runtime-isolation.md) | RepoRuntime Isolation Architecture | Superseded |
| [0007](0007-dashboard-api-multi-repo-scoping.md) | Dashboard API Architecture for Multi-Repo Scoping | Accepted |
| [0008](0008-multi-repo-dashboard-architecture.md) | Multi-Repo Dashboard Architecture | Accepted |
| [0009](0009-multi-repo-process-per-repo-model.md) | Multi-Repo Process-Per-Repo Model | Accepted |
| [0010](0010-worktree-and-path-isolation.md) | Worktree and Path Isolation Architecture | Accepted |
| [0011](0011-epic-release-creation-architecture.md) | Epic Release Creation Architecture | Accepted |
| [0012](0012-epic-merge-coordination-architecture.md) | Epic Merge Coordination Architecture | Accepted |
| [0013](0013-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Superseded |
| [0014](0014-session-counter-forward-progression-semantics.md) | Session Counter Forward-Progression Semantics | Accepted |
| [0015](0015-protocol-callback-gate-pattern.md) | Protocol-Based Callback Injection Gate Pattern | Accepted |
| [0016](0016-visual-validation-skipped-override-semantics.md) | VisualValidation SKIPPED Override Semantics | Accepted |
| [0017](0017-auto-decompose-triage-counter-exclusion.md) | Auto-Decompose Triage Counter Exclusion | Accepted |
| [0018](0018-screenshot-capture-pipeline.md) | Screenshot Capture Pipeline Architecture | Accepted |
| [0019](0019-background-task-delegation-abstraction-layer.md) | Background Task Delegation Abstraction Layer | Accepted |
| [0020](0020-autoApproveRow-border-context-awareness.md) | autoApproveRow Border Context Awareness | Superseded |
| [0021](0021-persistence-architecture-and-data-layout.md) | Persistence Architecture and Data Layout | Accepted |
| [0022](0022-integration-test-architecture-cross-phase.md) | Integration Test Architecture — Cross-Phase Pipeline Harness | Accepted |
| [0023](0023-dead-class-artifacts-in-mock-based-tests.md) | Require Instantiation Verification for Test-Local Classes | Accepted |
| [0024](0024-implementation-retry-recovery-architecture.md) | Implementation Retry Recovery Architecture | Accepted |
| [0025](0025-symmetric-field-assertion-checklist-shared-return-types.md) | Symmetric Field Assertion Checklist for Shared Return Types | Accepted |
| [0027](0027-duplicate-class-merge-artifact-pattern.md) | Duplicate Class Definitions — Merge-Artifact Pattern | Accepted |
| [0028](0028-event-driven-report-pipeline.md) | Event-Driven Report Pipeline with Extractable Widget | Accepted |
| [0029](0029-caretaker-loop-pattern.md) | Caretaker Background Loop Pattern | Accepted |
| [0030](0030-routes-domain-decomposition.md) | Dashboard Routes Domain Decomposition | Accepted |
| [0031](0031-product-track-architecture.md) | Product Track Architecture — Discover and Shape Phases | Superseded |
| [0032](0032-per-repo-wiki-knowledge-base.md) | Per-Repo Wiki Knowledge Base (Karpathy Pattern) | Accepted |
| [0033](0033-gate-triage-call-not-hitl-fallback.md) | Gate Triage Call on Config Toggle, Not Just HITL Fallback | Superseded |
| [0034](0034-auto-triage-toggle-must-gate-routing.md) | Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking | Accepted |
| [0035](0035-tests-must-match-toggle-state-they-assert.md) | Tests Must Match Toggle State They Assert | Accepted |
| [0036](0036-cli-argparse-config-builder-pattern.md) | CLI Architecture — argparse with Config Builder Pattern | Superseded |
| [0037](0037-supersession-regex-all-verb-forms.md) | Supersession Regex Must Include All Verb Forms | Accepted |
| [0038](0038-multi-repo-architecture-wiring-pattern.md) | Multi-Repo Architecture Wiring Pattern | Proposed |
| [0039](0039-stats-counter-placement-in-delegating-helpers.md) | Stats Counter Placement in Delegating Helpers | Rejected |
| [0040](0040-adr-reviewer-proposed-only-filter.md) | ADR Reviewer Proposed-Only Filter and Validator Scope | Rejected |
| [0041](0041-github-source-of-truth-cache-as-sidecar.md) | GitHub as Source of Truth, Local Cache as Sidecar | Accepted |
| [0042](0042-two-tier-branch-release-promotion.md) | Two-tier branch model with automated release-candidate promotion | Accepted |
| [0043](0043-dynamic-plugin-skill-loading.md) | Dynamic plugin skill loading — install at boot, discipline in the prompt, filtered per phase | Accepted |
| [0044](0044-hydraflow-principles.md) | HydraFlow Principles — the audit contract for new and existing repos | Proposed |
| [0045](0045-trust-architecture-hardening.md) | Trust Architecture Hardening — Lights-Off Trust Fleet (10 loops + 2 non-loop subsystems) | Accepted |
| [0046](0046-meta-observability-bounded-recursion.md) | Meta-observability with bounded recursion — one layer of meta, no more | Proposed |
| [0047](0047-fake-adapter-contract-testing-cassettes.md) | Fake-adapter contract testing via cassette record/replay | Accepted |
| [0048](0048-auto-revert-on-rc-red.md) | Auto-revert on RC red (extends ADR-0042) | Proposed |
| [0049](0049-trust-loop-kill-switch-convention.md) | Trust-loop kill-switch convention (`enabled_cb` only, no config-only) | Accepted |
| [0050](0050-auto-agent-hitl-preflight.md) | Auto-Agent HITL Pre-Flight Loop | Accepted |
| [0051](0051-iterative-production-readiness-review.md) | Iterative production-readiness review | Accepted |
| [0052](0052-sandbox-tier-scenarios.md) | Sandbox-tier scenario testing | Accepted |
| [0053](0053-ubiquitous-language-as-living-artifact.md) | Ubiquitous Language as a Living Artifact | Accepted |
| [0054](0054-term-auto-proposer-loop.md) | Term Auto-Proposer Loop (Dark-Factory Glossary Growth) | Accepted |
| [0055](0055-otel-honeycomb-instrumentation.md) | OpenTelemetry Instrumentation as the Telemetry Layer | Superseded |
| [0056](0056-adr-touchpoint-gate-to-caretaker-loop.md) | ADR touchpoint enforcement — synchronous gate → asynchronous caretaker loop | Superseded |
| [0057](0057-term-pruner-loop.md) | Term-Pruner Loop (Dark-Factory Glossary Hygiene) | Accepted |
| [0058](0058-edge-proposer-loop.md) | Edge-Proposer Loop (Dark-Factory Graph Densification) | Accepted |
| [0059](0059-advisor-pattern-self-repairing-review.md) | Advisor Pattern — Self-Repairing Review | Proposed |
| [0060](0060-atlas-graph-view-and-provenance.md) | Atlas Graph View and Provenance | Accepted |
| [0061](0061-atlas-entries-as-evidence.md) | Atlas Entries as Evidence | Accepted |
| [0062](0062-entry-evidence-loop.md) | Entry-Evidence Loop | Accepted |
| [0063](0063-factory-phase-drift-mitigation.md) | Factory-Phase Drift Mitigation | Proposed |
| [0064](0064-earlier-adversarial-pipeline.md) | Earlier Adversarial Pipeline | Accepted |
| [0065](0065-remove-code-grooming-loop.md) | Remove CodeGroomingLoop | Accepted |
| [0066](0066-agent-port.md) | AgentPort: Dependency-Injection Boundary for Agent Runner | Proposed |
| [0067](0067-issue-fetcher-port.md) | IssueFetcherPort: GitHub Issue Fetching Boundary | Proposed |
| [0068](0068-bot-pr-port.md) | BotPRPort: Minimal Interface for Caretaker Bot-PRs | Proposed |
| [0069](0069-workspace-gc-loop.md) | WorkspaceGCLoop: Autonomous Worktree Garbage Collection | Proposed |
| [0070](0070-review-insight-store-port.md) | ReviewInsightStorePort: Persistence Boundary for Review Feedback Patterns | Proposed |
| [0071](0071-route-back-counter-port.md) | RouteBackCounterPort: Testable Counter for Precondition Route-Backs | Accepted |
| [0072](0072-stale-issue-loop.md) | StaleIssueLoop: Auto-Close Stale General Issues | Proposed |
| [0073](0073-runs-gc-loop.md) | RunsGCLoop: Artifact Retention Enforcement | Proposed |
| [0074](0074-retrospective-loop.md) | RetrospectiveLoop: Durable-Queue Pattern Analysis | Proposed |
| [0075](0075-merge-state-watcher-loop.md) | MergeStateWatcherLoop: Autonomous Conflict Detection and Rebase | Proposed |
| [0076](0076-github-cache-loop.md) | GitHubCacheLoop: Centralized GitHub Data Cache | Proposed |
| [0077](0077-pr-unsticker-loop.md) | PRUnstickerLoop: Goal-Driven HITL PR Resolution | Proposed |
| [0078](0078-pricing-refresh-loop.md) | PricingRefreshLoop: Autonomous LLM Pricing Drift Detection | Proposed |
| [0079](0079-adr-reviewer-loop.md) | ADRReviewerLoop: Autonomous Panel Review for Proposed ADRs | Proposed |
| [0080](0080-epic-monitor-loop.md) | EpicMonitorLoop: Autonomous Stale-Epic Detection and Progress Refresh | Proposed |
| [0081](0081-epic-sweeper-loop.md) | EpicSweeperLoop: Autonomous Completion-Based Epic Auto-Close | Proposed |
| [0082](0082-declarative-gate-contract.md) | Declarative Gate Contract for Branch Protection | Proposed |
| [0083](0083-no-ignored-test-gates.md) | No ignored automated test gates | Accepted |
| [0084](0084-auto-agent-universal-root-cause-gate.md) | Auto-Agent as a Universal, Persistent, Root-Cause HITL Gate | Proposed |
| [0085](0085-secrets-never-persist-in-audit-stream.md) | Secrets never persist in the canonical audit stream | Accepted |
| [0086](0086-live-corpus-replay-loop.md) | LiveCorpusReplayLoop: Shadow-Corpus Drift Detection | Proposed |
| [0087](0087-prompt-structure-standard.md) | Prompt structure standard (XML tags, 8-criterion rubric, mechanical scoring) | Accepted |
| [0088](0088-label-drift-caretaker-loop.md) | LabelDriftWatcherLoop — Cross-Entity State-Machine Drift Caretaker | Accepted |
| [0089](0089-memory-backlog-loop.md) | MemoryBacklogLoop — promote session-memory feedback to the find queue | Accepted |
| [0090](0090-atlas-knowledge-graph-dashboard.md) | Atlas — Knowledge Graph Dashboard Surface | Accepted |
| [0091](0091-epic-monitor-completion-sweep.md) | Fold Epic Completion Sweep into Epic Monitor | Superseded |
| [0092](0092-untrusted-text-trust-boundary.md) | Untrusted-text trust boundary for agent prompts | Accepted |
| [0093](0093-loop-fitness-as-measured-contract.md) | Loop fitness as a measured contract | Accepted |
| [0094](0094-two-level-convergence-gate-and-ledger.md) | Two-level convergence: Gate + ConvergenceLedger | Accepted |
| [0095](0095-approve-path-gating-and-converged.md) | Approve-path gating and live convergence (Phase 2a) | Accepted |
| [0096](0096-boundary-verdict-recording.md) | Boundary verdict recording (Phase 2b) | Accepted |
| [0097](0097-attempt-counter-migration-to-ledger.md) | Attempt counter migration into the ledger (Phase 2c) | Accepted |
| [0098](0098-convergence-oscillation-caretaker.md) | Convergence oscillation caretaker (Phase 2d) | Accepted |
| [0099](0099-orchestration-as-a-control-system.md) | Orchestration as a Control System | Accepted |
| [0100](0100-adr-conformance-as-a-measured-contract.md) | ADR conformance as a measured contract | Accepted |
| [0101](0101-disturbance-dampener.md) | Disturbance Dampener — feedforward ratchet + burn-down loop | Proposed |
| [0102](0102-convergence-gate-general-availability.md) | Convergence gate general availability (flag removed) | Accepted |
| [0103](0103-continuous-human-steering-channel.md) | Continuous Human-on-the-Loop Steering Channel | Accepted |
| [0104](0104-auto-tightening-ratchet.md) | Auto-tightening ratchet | Accepted |
| [0105](0105-autonomous-convergence-via-decomposition.md) | Autonomous Convergence via Decomposition | Proposed |
| [0106](0106-thread-level-event-loop-freeze-detector.md) | Thread-level event-loop freeze detector | Accepted |
| [0107](0107-collapse-discover-shape-into-plan.md) | Collapse Discover + Shape into Plan — Triage → Plan Directly | Accepted |
| [0108](0108-deterministic-simulation-fault-injection-evaluation.md) | Deterministic-Simulation Fault Injection on the Sandbox Compose — Evaluation | Proposed |
| [0109](0109-ultra-review-opt-in-deep-review-tier.md) | Opt-in "ultra" deep-review tier for the review phase | Accepted |
| [0110](0110-provider-harness-backend-split.md) | Provider/Harness Backend Split — z.ai as a Claude-harness backend | Accepted |
| [0111](0111-in-framework-flow-dag-runtime.md) | In-framework flow (DAG) runtime for workers and phases | Accepted |
| [0112](0112-per-issue-isolation-via-local-git-clone.md) | Per-Issue Isolation via Local Git Clone | Accepted |
| [0113](0113-adr-lineage-precedent-and-divergence.md) | ADR lineage — Precedent and Divergence lines | Accepted |
| [0114](0114-optional-per-type-eventbus-subscription.md) | Optional per-type EventBus subscription | Accepted |
| [0115](0115-auto-diagnose-before-human-for-audit-and-escape-surfaces.md) | Auto-diagnose before human for audit + escape surfaces | Accepted |
| [0116](0116-prompts-as-a-measured-contract.md) | Prompts as a measured contract | Accepted |
| [0117](0117-observed-prompt-coverage.md) | Observed prompt coverage — the denominator is measured, not inferred | Accepted |
| [0118](0118-observability-belongs-to-the-sre-agent-not-the-loops.md) | Observability belongs to the SRE agent, not the loops | Accepted |
| [0119](0119-credit-failover-to-glm.md) | Credit failover — reroute work to GLM instead of pausing when Claude credits are exhausted | Accepted |
| [0120](0120-stillness-control-architecture.md) | The stillness control architecture — setpoint regulators, an optimization layer, and innovation-filtered sensing | Proposed |
| [0121](0121-rails-manifest-and-drift-caretaker.md) | Rails manifest (rails.yaml) + drift caretaker — template conformance as data | Proposed |
| [0122](0122-vocabulary-scopes-for-the-three-assurance-disciplines.md) | Vocabulary scopes for the three assurance disciplines | Proposed |
| [0123](0123-bidirectional-enforcement.md) | Bidirectional enforcement — every rule declares which direction it binds | Proposed |
| [0124](0124-tier-2-goal-supervisor.md) | Tier-2 goal supervisor — a Fable "mini-me" over Tier-1's liveness signals | Proposed |
| [0125](0125-mutation-gauntlet-gate-sensitivity.md) | Mutation gauntlet — measuring gate sensitivity by injecting known faults | Proposed |
| [0126](0126-golden-baseline-finder-calibration.md) | Golden-baseline finder calibration — measuring a generative finder's noise floor | Proposed |
| [0127](0127-judge-calibration.md) | Judge calibration — scoring a judge's verdicts against outcomes with proper scoring rules | Proposed |
| [0128](0128-external-security-review-anchor.md) | External Claude security-review Action as an out-of-band assurance anchor | Proposed |
| [0129](0129-adr-checkable-assertion-density.md) | Checkable-assertion density as an ADR setpoint-erosion series | Proposed |
| [0130](0130-prompt-outcome-pairing.md) | Prompt outcome pairing — make the form rubric ungameable before a floor | Proposed |
| [0131](0131-spec-intake-gate.md) | Spec intake gate — stress-testing prose before it becomes a setpoint | Proposed |
| [0132](0132-cognitive-process-constitution.md) | The cognitive-process constitution — the harness as a governor of thought | Proposed |
| [0133](0133-vitals-methodology-multiplicity-mde-tbe.md) | Vitals methodology — widened-limit multiplicity, published MDE, and time-between-events charts | Proposed |
| [0134](0134-per-repo-model-harness-selection.md) | Per-repo model/harness selection — run Claude and GLM projects side by side | Accepted |
| [0135](0135-factory-as-launchd-service-operator-stop-latch.md) | Factory runs as a launchd service; operator Stop is a latch honoured by autostart and the liveness kernel | Accepted |
| [0136](0136-adr-drift-enforcement-deterministic-citation-gate.md) | ADR drift enforcement is a deterministic cited-symbol CI gate, not a caretaker loop | Accepted |
| [0137](0137-fenced-issue-driver-and-director-runtime-boundary.md) | Fenced IssueDriver and director runtime boundary | Accepted |
| [0138](0138-gateway-account-identity-and-sanitized-route-visibility.md) | Gateway account identity and sanitized route visibility | Accepted |
| [0139](0139-shadow-routing-policy-resolver.md) | Shadow routing policy resolver and hash-linked decision record | Accepted |
| [0140](0140-revision-safe-policy-workspace-and-operator-write-boundary.md) | Revision-safe policy workspace and the operator write boundary | Accepted |
| [0141](0141-bounded-reversible-routing-enforcement-canary.md) | Bounded, reversible routing enforcement — the resolve-and-mint canary | Accepted |
| [0142](0142-multi-account-pools-and-bounded-fallback.md) | Multi-account pools and bounded fallback | Accepted |

## Adding a new ADR

Increment the number and copy an existing ADR's metadata block (e.g.
[ADR-0002](0002-labels-as-state-machine.md) for a single check, or
[ADR-0049](0049-trust-loop-kill-switch-convention.md) / [ADR-0053](0053-ubiquitous-language-as-living-artifact.md)
for multiple), then fill in the sections. There is no separate template file.

Every **Accepted** ADR MUST declare an `**Enforcement:**` line — see the
[Enforcement](#enforcement) section above for the three kinds and what each
requires. The coverage ratchet blocks a new Accepted ADR that omits or
mis-declares it. When you choose `enforced`, get the `**Enforced by:**`
SHAPE right (this is the common footgun):

- Each check is TYPED: it starts with `pytest:` (e.g.
  `pytest:tests/test_foo.py` or `pytest:tests/test_foo.py::test_bar`) or
  `make:` (a non-mutating target). A bare or backtick-wrapped path parses as
  prose and fails the ratchet.
- ONE check goes inline on the marker: `**Enforced by:** pytest:tests/test_foo.py`.
- For MULTIPLE checks, put the marker on its own line and list one check per
  plain continuation line:

  ```
  **Enforced by:**
  pytest:tests/test_a.py
  pytest:tests/test_b.py
  ```

- Never repeat the `**Enforced by:**` marker (only the first is parsed, so the
  rest are silently dropped); never comma-join checks on one line.

Mark superseded ADRs by setting `**Status:** Superseded` and adding a `Superseded by: ADR-XXXX` entry in the Related section rather than deleting them.
