# ADR Checkable-Assertion Density

The **executable share** of each Accepted ADR's cited enforcement (`pytest` / `make` / `script` are executable assertions; `prose` is not). Frontmatter *presence* of enforcement is saturated and cannot move — this series tracks *how executable* that enforcement is, the erosion axis orthogonal to the REAL/WEAK/MISSING quality lens in [`adr-enforcement.md`](adr-enforcement.md). Density = executable checks / all cited checks.

## Population

- **Population:** Accepted (84 ADRs)
- **Mean density** (per-ADR, unweighted): 96%
- **Executable fraction** (check-weighted): 98% (168 of 171 cited checks)
- **Check kinds:** pytest 167, make 1, script 0, prose 3
- **Prose-count control limit** (Shewhart c-chart UCL): 0.60
- **Prose outliers** (non-executable enforcement anomalously concentrated — look here first): ADR-0025, ADR-0035, ADR-0051

> The monthly time-series and the shared Shewhart baseline framework are deferred to the epic's framework child (#10915). This surface is the per-PR snapshot; the longitudinal trend is a later phase.

## Per-ADR density

| ADR | Title | Density | Executable | Prose |
|-----|-------|--------:|-----------:|------:|
| ADR-0025 | Symmetric Field Assertion Checklist for Shared Return Types | 0% | 0 | 1 |
| ADR-0035 | Tests Must Match Toggle State They Assert | 0% | 0 | 1 |
| ADR-0051 | Iterative production-readiness review | 0% | 0 | 1 |
| ADR-0001 | Five Concurrent Async Loops | 100% | 2 | 0 |
| ADR-0002 | GitHub Labels as the Pipeline State Machine | 100% | 1 | 0 |
| ADR-0004 | CLI-based Agent Runtime (Claude / Codex / Pi.dev) | 100% | 2 | 0 |
| ADR-0005 | PR Recovery and Zero-Diff Branch Handling in Implement Phase | 100% | 1 | 0 |
| ADR-0007 | Dashboard API Architecture for Multi-Repo Scoping | 100% | 1 | 0 |
| ADR-0008 | Multi-Repo Dashboard Architecture | 100% | 1 | 0 |
| ADR-0009 | Multi-Repo Process-Per-Repo Model | 100% | 1 | 0 |
| ADR-0010 | Worktree and Path Isolation Architecture | 100% | 1 | 0 |
| ADR-0011 | Epic Release Creation Architecture | 100% | 2 | 0 |
| ADR-0012 | Epic Merge Coordination Architecture | 100% | 1 | 0 |
| ADR-0014 | Session Counter Forward-Progression Semantics | 100% | 1 | 0 |
| ADR-0015 | Protocol-Based Callback Injection for Merge-Phase Gates | 100% | 1 | 0 |
| ADR-0016 | VisualValidation SKIPPED Override Semantics — Partial Suppression by Design | 100% | 1 | 0 |
| ADR-0017 | Auto-Decompose Triage Path Excluded from Session Counter | 100% | 1 | 0 |
| ADR-0018 | Screenshot Capture Pipeline Architecture | 100% | 2 | 0 |
| ADR-0019 | Background Task Delegation — Call the Right Abstraction Layer | 100% | 2 | 0 |
| ADR-0021 | Persistence Architecture and Data Layout | 100% | 3 | 0 |
| ADR-0022 | Integration Test Architecture — Cross-Phase Pipeline Harness | 100% | 1 | 0 |
| ADR-0023 | Require Instantiation Verification for Test-Local Classes | 100% | 1 | 0 |
| ADR-0024 | Implementation Retry Recovery Architecture | 100% | 2 | 0 |
| ADR-0027 | Duplicate Class Definitions — Merge-Artifact Pattern | 100% | 1 | 0 |
| ADR-0028 | Event-Driven Report Pipeline with Extractable Widget | 100% | 1 | 0 |
| ADR-0029 | Caretaker Background Loop Pattern | 100% | 1 | 0 |
| ADR-0030 | Dashboard Routes Domain Decomposition | 100% | 1 | 0 |
| ADR-0032 | Per-Repo Wiki Knowledge Base (Karpathy Pattern) | 100% | 8 | 0 |
| ADR-0034 | Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking | 100% | 1 | 0 |
| ADR-0037 | Supersession Regex Must Include All Verb Forms | 100% | 1 | 0 |
| ADR-0041 | GitHub as Source of Truth, Local Cache as Sidecar | 100% | 2 | 0 |
| ADR-0042 | Two-tier branch model with automated release-candidate promotion | 100% | 1 | 0 |
| ADR-0043 | Dynamic plugin skill loading — install at boot, discipline in the prompt, filtered per phase | 100% | 2 | 0 |
| ADR-0045 | Trust Architecture Hardening — Lights-Off Trust Fleet | 100% | 3 | 0 |
| ADR-0047 | Fake-adapter contract testing via cassette record/replay | 100% | 2 | 0 |
| ADR-0049 | Trust-loop kill-switch convention (`enabled_cb` only, no config-only) | 100% | 2 | 0 |
| ADR-0050 | Auto-Agent HITL Pre-Flight Loop | 100% | 5 | 0 |
| ADR-0052 | Sandbox-tier scenario testing | 100% | 2 | 0 |
| ADR-0053 | Ubiquitous Language as a Living Artifact | 100% | 2 | 0 |
| ADR-0054 | Term Auto-Proposer Loop (Dark-Factory Glossary Growth) | 100% | 2 | 0 |
| ADR-0057 | Term-Pruner Loop (Dark-Factory Glossary Hygiene) | 100% | 2 | 0 |
| ADR-0058 | Edge-Proposer Loop (Dark-Factory Graph Densification) | 100% | 2 | 0 |
| ADR-0060 | Atlas — Graph View, ADR Nodes, and Term Provenance | 100% | 1 | 0 |
| ADR-0061 | Atlas — Wiki Entries as Term Evidence + Discovered Bucket | 100% | 1 | 0 |
| ADR-0062 | Entry-Evidence Loop — Term ↔ Wiki-Entry Backlinks (Dark-Factory Glossary Enrichment) | 100% | 2 | 0 |
| ADR-0064 | Earlier-Adversarial Pipeline — Surface Dissent Before Plan-Reviewer | 100% | 1 | 0 |
| ADR-0065 | Remove CodeGroomingLoop | 100% | 1 | 0 |
| ADR-0071 | RouteBackCounterPort: Testable Counter for Precondition Route-Backs | 100% | 1 | 0 |
| ADR-0083 | No ignored automated test gates | 100% | 2 | 0 |
| ADR-0085 | Secrets never persist in the canonical audit stream | 100% | 2 | 0 |
| ADR-0087 | Prompt structure standard (XML tags, 8-criterion rubric, mechanical scoring) | 100% | 2 | 0 |
| ADR-0088 | LabelDriftWatcherLoop — Cross-Entity State-Machine Drift Caretaker | 100% | 2 | 0 |
| ADR-0089 | MemoryBacklogLoop — promote session-memory feedback to the find queue | 100% | 3 | 0 |
| ADR-0090 | Atlas — Knowledge Graph Dashboard Surface | 100% | 1 | 0 |
| ADR-0092 | Untrusted-text trust boundary for agent prompts | 100% | 4 | 0 |
| ADR-0093 | Loop fitness as a measured contract | 100% | 1 | 0 |
| ADR-0094 | Two-level convergence: Gate + ConvergenceLedger | 100% | 4 | 0 |
| ADR-0095 | Approve-path gating and live convergence (Phase 2a) | 100% | 4 | 0 |
| ADR-0096 | Boundary verdict recording (Phase 2b) | 100% | 1 | 0 |
| ADR-0097 | Attempt counter migration into the ledger (Phase 2c) | 100% | 1 | 0 |
| ADR-0098 | Convergence oscillation caretaker (Phase 2d) | 100% | 1 | 0 |
| ADR-0099 | HydraFlow Orchestration as a Control System | 100% | 1 | 0 |
| ADR-0100 | ADR conformance as a measured contract | 100% | 1 | 0 |
| ADR-0102 | Convergence gate general availability (flag removed) | 100% | 1 | 0 |
| ADR-0103 | Continuous Human-on-the-Loop Steering Channel | 100% | 6 | 0 |
| ADR-0104 | Auto-tightening ratchet | 100% | 1 | 0 |
| ADR-0106 | Thread-level event-loop freeze detector | 100% | 2 | 0 |
| ADR-0107 | Collapse Discover + Shape into Plan — Triage → Plan Directly | 100% | 1 | 0 |
| ADR-0109 | Opt-in "ultra" deep-review tier for the review phase | 100% | 1 | 0 |
| ADR-0110 | Provider/Harness Backend Split — z.ai as a Claude-harness backend | 100% | 1 | 0 |
| ADR-0111 | In-framework flow (DAG) runtime for workers and phases | 100% | 1 | 0 |
| ADR-0112 | Per-Issue Isolation via Local Git Clone | 100% | 1 | 0 |
| ADR-0113 | ADR lineage — Precedent and Divergence lines | 100% | 1 | 0 |
| ADR-0114 | Optional per-type EventBus subscription | 100% | 1 | 0 |
| ADR-0115 | Auto-diagnose before human for audit + escape surfaces | 100% | 7 | 0 |
| ADR-0116 | Prompts as a measured contract | 100% | 4 | 0 |
| ADR-0117 | Observed prompt coverage — the denominator is measured, not inferred | 100% | 1 | 0 |
| ADR-0118 | Observability belongs to the SRE agent, not the loops | 100% | 1 | 0 |
| ADR-0119 | Credit failover — reroute work to GLM instead of pausing when Claude credits are exhausted | 100% | 1 | 0 |
| ADR-0134 | Per-repo model/harness selection — run Claude and GLM projects side by side | 100% | 5 | 0 |
| ADR-0135 | Factory runs as a launchd service; operator Stop is a latch honoured by autostart and the liveness kernel | 100% | 8 | 0 |
| ADR-0136 | ADR drift enforcement is a deterministic cited-symbol CI gate, not a caretaker loop | 100% | 2 | 0 |
| ADR-0137 | Fenced IssueDriver and director runtime boundary | 100% | 8 | 0 |
| ADR-0138 | Gateway account identity and sanitized route visibility | 100% | 8 | 0 |


<!-- arch:generated -->
