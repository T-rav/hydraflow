"""Trust-fleet loop dials, lifted out of ``HydraFlowConfig`` (#11547).

``src/config.py`` is the largest god class on the erosion board, and its mass
is not methods: 638 of its statements are field declarations spanning ~4,800
lines, against 49 methods in ~540. So the remedy is to move *fields*, and the
first cohesive cluster out is the trust fleet — twenty consecutive sections
that each name their own loop.

**Three mixins, not one.** The cluster is 649 lines; parking it in a single
class would have created a 651-LOC god class and traded one erosion entry for
another. Split at boundaries the cluster already had, each part is a coherent
set well under threshold.

A mixin, not a nested model: every field keeps its exact name, type, default
and constraints on ``HydraFlowConfig`` itself, so ``config.flake_tracker_interval``
and ``HydraFlowConfig.model_fields["flake_tracker_interval"]`` are unchanged and
no caller moves.

Verified by fingerprinting all 659 fields — annotation, default, default
factory, constraint metadata, alias, frozen, exclude, description — plus the
field- and model-validator sets, before and after: identical.

**Read ``arch/config_surface.py`` before moving another cluster.** Three arch
readers derive published artifacts from ``config.py`` by parsing it as a file,
and had to learn to follow the config across modules first (#12140). Nineteen
loop-interval defaults and three ``*_model`` role fields live in this module
now; under the old readers every one of those loops rendered its tick interval
as ``—`` in the published loop registry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TrustFleetHealthDials(BaseModel):
    """Fleet-health sensors: is the machine still working, and is it honest?

    LoopFitnessScorecard, FlakeTracker, SkillPromptEval and its prompt
    self-refinement, FakeCoverageAuditor, AdrConformance, MemoryBacklog,
    RCBudget, WikiRotDetector, and the AutoTighten ratchet caretaker.
    """

    # Trust fleet — LoopFitnessScorecard (spec §5)
    fitness_scorecard_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between loop-fitness scorecard cycles",
    )
    fitness_window_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Rolling window (days) over which loop fitness is computed",
    )
    fitness_min_samples: int = Field(
        default=5,
        ge=1,
        le=10000,
        description=(
            "Min samples before a SCORED loop reports OK confidence. "
            "Right-sized to observed proposer throughput (6-14 filed per "
            "30-day window; #9841 — the old default of 20 was unreachable "
            "and every scorecard row stayed insufficient_data forever). "
            "Loops additionally cap this at their cadence-achievable sample "
            "count via loop_fitness.cadence_min_samples."
        ),
    )

    # Trust fleet — FlakeTrackerLoop (spec §4.5)
    flake_tracker_interval: int = Field(
        default=14400,
        ge=3600,
        le=2_592_000,
        description="Seconds between FlakeTrackerLoop ticks (default 4h)",
    )
    flake_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Flake count in last 20 runs that triggers an issue (>=)",
    )
    xdist_quarantine_threshold: int = Field(
        default=2,
        ge=1,
        le=20,
        description=(
            "xdist-audit runs a test must be flagged fail-parallel/pass-serial "
            "in before FlakeTrackerLoop files a quarantine issue (>=)"
        ),
    )

    # Trust fleet — SkillPromptEvalLoop (spec §4.6)
    skill_prompt_eval_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between SkillPromptEvalLoop ticks (default 7d)",
    )
    skill_prompt_eval_max_corpus_cases: int = Field(
        default=500,
        ge=10,
        le=10_000,
        description=(
            "Defense-in-depth cap on adversarial corpus cases per weekly "
            "tick. Forwarded to the harness via HYDRAFLOW_TRUST_ADVERSARIAL_"
            "MAX_CASES (pre-spend) and applied as a Python-side sample "
            "(post-output) to bound operator-visible escalation flooding "
            "if the harness misses the env var."
        ),
    )
    skill_prompt_eval_live_case_budget: int = Field(
        default=12,
        ge=0,
        le=500,
        description=(
            "Max catcher-skill corpus cases a LIVE weekly backstop run "
            "evaluates via the per-skill live path (each builds its own "
            "skill's prompt and makes one real agent-CLI call; round-robin "
            "across skills). Forwarded to the corpus runner via HYDRAFLOW_"
            "TRUST_ADVERSARIAL_LIVE_BUDGET; inert unless HYDRAFLOW_TRUST_"
            "ADVERSARIAL_LIVE=1. 0 disables the per-skill live path. Keep "
            "aligned with corpus_runner.DEFAULT_LIVE_BUDGET (#10014)."
        ),
    )
    skill_prompt_eval_adversarial_timeout_seconds: int = Field(
        default=3600,
        ge=60,
        le=21600,
        description=(
            "Hard cap (seconds) on the `make trust-adversarial` subprocess "
            "read in SkillPromptEvalLoop (default 1h; also bounds the "
            "per-skill live refine-validation runner). Healthy runtime "
            "scales with corpus/repo size, so this is an operator knob, not "
            "a constant (#9555): too low silently degrades the weekly "
            "backstop to a permanent no-op (false timeout every tick); too "
            "high weakens wedged-child protection."
        ),
    )

    # Trust fleet — prompt self-refinement (#9724)
    skill_prompt_refine_enabled: bool = Field(
        default=True,
        description="Deploy-time kill-switch for skill-prompt self-refinement proposals.",
    )
    skill_prompt_refine_max_weekly: int = Field(
        default=2,
        ge=0,
        le=50,
        description="Max refine proposals filed per rolling 7-day window.",
    )
    skill_prompt_refine_model: str = Field(
        default="",
        description=(
            "Model override for skill-prompt refinement generation. "
            "Empty falls back to the maintenance model, then the background "
            "model, then 'sonnet'."
        ),
    )
    skill_prompt_refine_live_validation_budget: int = Field(
        default=4,
        ge=0,
        le=50,
        description=(
            "Max cases (the regressed case + a sample of that skill's own "
            "held-out honeypots) a refine-candidate live re-validation run "
            "forces through the real agent CLI instead of the "
            "expected_transcript.txt fixture — proving the candidate patch "
            "actually changed prompt->transcript behavior for the better, "
            "not just against the OLD prompt's canned transcript. Forwarded "
            "to the corpus runner via the `--force-live-cases` CLI flag; "
            "inert unless the operator has also set HYDRAFLOW_TRUST_"
            "ADVERSARIAL_LIVE=1 on the loop's environment (the same "
            "operator opt-in the weekly live backstop uses). 0 disables the "
            "sample — every validation case replays its fixture, matching "
            "pre-#10063 behavior. Distinct from "
            "skill_prompt_eval_live_case_budget (the weekly full-corpus "
            "backstop's budget): refine validation runs once per candidate "
            "attempt over a handful of cases, not the whole corpus (#10063)."
        ),
    )

    # Trust fleet — FakeCoverageAuditorLoop (spec §4.7)
    fake_coverage_auditor_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between FakeCoverageAuditorLoop ticks (default 7d)",
    )

    # Trust fleet — AdrConformanceLoop (ADR-0100)
    adr_conformance_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between AdrConformanceLoop ticks (default 24h)",
    )

    # Trust fleet — MemoryBacklogLoop (ADR-0089)
    memory_backlog_interval_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Cadence for MemoryBacklogLoop (default 24h, range 1h–7d).",
    )
    memory_backlog_max_issues_per_tick: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Max memory-backlog issues MemoryBacklogLoop files in one tick "
            "(#10777). A batch of newly-pending mirror entries would otherwise "
            "file one issue each; over-cap entries are folded into a single "
            "summary issue instead."
        ),
    )
    memory_backlog_label: list[str] = Field(
        default=["hydraflow-memory-backlog"],
        description=(
            "Label applied to issues filed by MemoryBacklogLoop (alongside find_label)."
        ),
    )
    memory_backlog_stuck_label: list[str] = Field(
        default=["hydraflow-memory-backlog-stuck"],
        description=(
            "Escalation label after 3 unresolved attempts on the same memory entry."
        ),
    )

    # Trust fleet — RCBudgetLoop (spec §4.8)
    rc_budget_interval: int = Field(
        default=14400,
        ge=3600,
        le=604800,
        description="Seconds between RCBudgetLoop ticks (default 4h)",
    )
    rc_budget_threshold_ratio: float = Field(
        default=1.5,
        ge=1.0,
        le=5.0,
        description=(
            "Multiplier vs. 30-day rolling median; current_s >= ratio * median_s fires."
        ),
    )
    rc_budget_spike_ratio: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description=(
            "Multiplier vs. max(recent 5 excl. current); "
            "current_s >= ratio * recent_max fires."
        ),
    )

    # Trust fleet — WikiRotDetectorLoop (spec §4.9)
    wiki_rot_detector_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between WikiRotDetectorLoop ticks (default 7d)",
    )
    wiki_rot_detector_max_issues_per_tick: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Finding-rate budget: max hydraflow-find issues WikiRotDetectorLoop "
            "files in one tick across all repos and cite styles (#10767). Cites "
            "over the cap are summarized into a SINGLE issue instead of one "
            "each. Gates FILING only — ``broken_subjects`` accumulation is never "
            "capped, so ``reconcile_open`` cannot wrongly auto-close a live "
            "escalation for a merely rate-limited cite (patterns/0576)."
        ),
    )

    # Caretaker — AutoTightenLoop (auto-tightening ratchet)
    auto_tighten_stability_ticks: int = Field(default=3, ge=1)
    auto_tighten_coverage_margin: float = Field(default=1.0, ge=0.0)
    auto_tighten_interval: int = Field(default=86400, ge=60)


class TrustFleetVocabularyDials(BaseModel):
    """The ubiquitous-language loops (ADR-0053 et al).

    TermProposer, TermPruner, EdgeProposer, EntryEvidence and CorpusLearning
    — the loops that grow and prune the glossary, and the corpus it is
    learned from.
    """

    # Trust fleet — TermProposerLoop (ADR-0054)
    term_proposer_enabled: bool = Field(
        default=True,
        description="Kill-switch for TermProposerLoop (ADR-0054).",
    )
    term_proposer_interval: int = Field(
        default=14400,
        ge=3600,
        le=86400,
        description="Seconds between TermProposerLoop ticks.",
    )
    term_proposer_max_per_tick: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max term drafts produced per tick.",
    )
    term_proposer_cooldown_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Cooldown before retrying a candidate that previously failed validation or LLM draft.",
    )
    term_proposer_model: str = Field(
        default="sonnet",
        description="Model for the term-proposer / entry-evidence drafters.",
    )
    term_proposer_tool: Literal["claude", "codex"] = Field(
        default="claude",
        description="CLI backend for the term-proposer drafters (claude path only).",
    )
    term_proposer_timeout: int = Field(
        default=180,
        ge=30,
        le=1800,
        description="Per-call timeout (seconds) for the term-proposer drafters.",
    )

    # Trust fleet — TermPrunerLoop (ADR-0057)
    term_pruner_enabled: bool = Field(
        default=True,
        description="Kill-switch for TermPrunerLoop (ADR-0057).",
    )
    term_pruner_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between TermPrunerLoop ticks.",
    )

    # Trust fleet — EdgeProposerLoop (ADR-0058)
    edge_proposer_enabled: bool = Field(
        default=True,
        description="Kill-switch for EdgeProposerLoop (ADR-0058).",
    )
    edge_proposer_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between EdgeProposerLoop ticks.",
    )

    # Trust fleet — EntryEvidenceLoop (ADR-0062)
    entry_evidence_enabled: bool = Field(
        default=True,
        description="Kill-switch for EntryEvidenceLoop (ADR-0062).",
    )
    entry_evidence_interval: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Seconds between EntryEvidenceLoop ticks.",
    )
    entry_evidence_max_entries_per_tick: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Max wiki entries the loop sends to the LLM per tick — bounds "
            "credit cost. Untracked entries roll over to the next tick."
        ),
    )

    # Trust fleet — CorpusLearningLoop (spec §4.1 v2)
    corpus_learning_interval: int = Field(
        default=3600,
        ge=3600,
        le=2_592_000,
        description=(
            "Seconds between CorpusLearningLoop ticks (default 1h, "
            "spec §4.1: the loop is reactive on new escape issues, so "
            "frequent ticks pick them up quickly)"
        ),
    )
    corpus_learning_signal_labels: tuple[str, ...] = Field(
        default=("skill-escape", "discover-escape", "shape-escape"),
        description=(
            "Escape-signal labels CorpusLearningLoop reads. Spec §4.1: covers "
            "skill-escape (post-impl), discover-escape (Discover §4.10), and "
            "shape-escape (Shape §4.10). Override for a stripped-down deployment."
        ),
    )
    corpus_learning_max_prs_per_tick: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Max PRs CorpusLearningLoop opens per tick. Bounds blast radius "
            "when escape-signal dedup misses (e.g. issue retitled mid-tick). "
            "Surplus validated cases defer to the next tick."
        ),
    )
    corpus_learning_synthesis_model: str = Field(
        default="opus",
        description=(
            "LLM model the CorpusLearningLoop uses to synthesize new "
            "adversarial cases (spec §4.1 v2). Must be distinct from "
            "the production post-impl skill model — synthesizing with "
            "the same model that the corpus is meant to test creates "
            "correlated failure (the synthesis model's blind spots "
            "won't surface in the corpus). Default `opus` against "
            "production `sonnet`."
        ),
    )
    disturbance_dampener_enabled: bool = Field(
        default=False,
        description="Enable the DisturbanceDampenerLoop burn-down loop (ADR-0095). Dark by default.",
    )
    disturbance_dampener_interval_seconds: int = Field(
        default=3600,
        description="DisturbanceDampenerLoop tick interval in seconds.",
    )
    disturbance_dampener_max_prs_per_tick: int = Field(
        default=1,
        description="Max burn-down PRs DisturbanceDampenerLoop opens per tick. Bounds blast radius.",
    )


class TrustFleetSteeringDials(BaseModel):
    """Steering, contracts, and the fleet's own sanity check.

    Human-on-the-loop continuous steering (ADR-0099 surface #4),
    ContractRefreshLoop, and TrustFleetSanityLoop.
    """

    # Human-on-the-loop continuous steering (ADR-0099 surface #4)
    human_steering_enabled: bool = Field(
        default=True,
        description=(
            "Enable the HumanSteeringLoop sensor for continuous human-on-the-loop "
            "steering (ADR-0099 #4). Default-on: safe because an empty "
            "human_steering_authorized_users allowlist honors nobody, so the "
            "sensor is inert until an operator login is explicitly allow-listed. "
            "Set HYDRAFLOW_HUMAN_STEERING_ENABLED=false to disable at deploy time."
        ),
    )
    human_steering_interval_seconds: int = Field(
        default=60,
        description="HumanSteeringLoop tick interval in seconds.",
    )
    human_steering_max_redos: int = Field(
        default=3,
        description="Max redo directives HumanSteeringLoop honors per issue before capping to prevent infinite redo.",
    )
    human_steering_authorized_users: list[str] = Field(
        default_factory=list,
        description="GitHub logins authorized to issue human-steering directives. Empty list honors nobody (safe default-on).",
    )

    # Trust fleet — ContractRefreshLoop (spec §4.2)
    contract_refresh_interval: int = Field(
        default=604800,
        ge=86400,
        le=2_592_000,
        description="Seconds between ContractRefreshLoop cycles (default 7 days)",
    )
    max_fake_repair_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Max per-adapter consecutive drift ticks before ContractRefreshLoop "
            "escalates a fake-drift issue to hitl-escalation (spec §4.2 Task 18)."
        ),
    )
    max_convergence_laps: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Maximum outer-convergence laps allowed before a ConvergenceLedger "
            "escalates an issue (ADR-0094)."
        ),
    )
    convergence_oscillation_interval: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description=(
            "Seconds between ConvergenceOscillationLoop ticks (default 1h). "
            "Must be between 5 minutes and 24 hours."
        ),
    )
    convergence_oscillation_loop_enabled: bool = Field(
        default=True,
        description=(
            "Enable the ConvergenceOscillationLoop caretaker that scans "
            "ConvergenceLedgers for cross-boundary oscillation and escalates "
            "stuck issues to HITL."
        ),
    )
    convergence_oscillation_window: int = Field(
        default=2,
        ge=2,
        le=10,
        description=(
            "Number of recent lap signatures to compare when detecting temporal "
            "outer oscillation (detect_outer_oscillation window parameter)."
        ),
    )
    convergence_oscillation_min_loopback_stages: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "Minimum number of distinct boundary stages (triage/shape/plan) "
            "that must have last_verdict==LOOP_BACK to trigger snapshot "
            "oscillation escalation."
        ),
    )
    convergence_oscillation_max_issues_per_tick: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Max HITL oscillation issues ConvergenceOscillationLoop files in "
            "one tick (#10777). Ledgers scale with in-flight issues; over-cap "
            "oscillating ledgers are deferred (NOT marked escalated) and "
            "retried next tick — a rate limit on filing volume, not a drop."
        ),
    )
    contracts_sandbox_repo: str = Field(
        default="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
        description=(
            "GitHub slug for the sandbox repo ContractRefreshLoop's "
            "FakeGitHub recorder hits when re-recording cassettes "
            "(spec §8). Override if the sandbox org is renamed."
        ),
    )
    vitals_emit_enabled: bool = Field(
        default=True,
        description=(
            "Emit this factory's vitals document to a local append-only spool "
            "(#11690). Layer 2 transport only: the document goes to "
            "``<data_root>/vitals/spool.jsonl`` and an adapter OUTSIDE "
            "HydraFlow ships it, so changing sink is never a HydraFlow change. "
            "Emission runs on the factory host, not CI, because the document's "
            "value is its identity (repo / head_sha / host) and a CI runner "
            "would stamp the wrong one."
        ),
    )

    vitals_emit_floor_hours: float = Field(
        default=24.0,
        ge=0.0,
        description=(
            "Emit a vitals reading if this many hours have passed since the "
            "last one, even with no RC cut (#11690 decision D2). The floor is "
            "what keeps a quiet factory distinguishable from a dead one — the "
            "single thing a push-based aggregate cannot infer for itself. "
            "0 disables the floor, leaving RC cuts as the only trigger."
        ),
    )

    contract_refresh_external_recorders: tuple[str, ...] = Field(
        default=("github", "docker", "claude"),
        description=(
            "Which of ContractRefreshLoop's external recorders may run when "
            "``contract_refresh_external_enabled`` is on. Selected by name so "
            "one recorder can be silenced without taking the others with it — "
            "#11830 turned all three off to stop one, which a sampled "
            "re-audit flagged as a scope mismatch (#11837).\n\n"
            "Defaults to all three. The github recorder is skipped separately "
            "while ``contracts_sandbox_repo`` is still its placeholder default "
            "(that slug 404s, #11821); pointing it at a real repo is what "
            "re-enables it, so the skip tracks the diagnosed defect — an "
            "unreachable TARGET — rather than blaming the recorder."
        ),
    )

    contract_refresh_external_enabled: bool = Field(
        default=False,
        description=(
            "Run ContractRefreshLoop's external recorders (github → "
            "contracts-sandbox repo, claude → api.anthropic.com, docker → "
            "alpine image pull). Disabling skips them so the loop completes "
            "fast in the air-gapped sandbox (only the local git recorder "
            "runs); each external recorder otherwise blocks up to the 120s "
            "subprocess timeout.\n\n"
            "Defaults to FALSE since #11821. The github recorder targets "
            "``contracts_sandbox_repo``, whose default "
            "(``T-rav-Hydra-Ops/hydraflow-contracts-sandbox``) returns 404 — "
            "so the shipped default sent every install into a recorder that "
            "could never succeed, warning once per cycle and reading as "
            "background noise. Operator decision, 2026-08-30: turn it off "
            "rather than leave it failing.\n\n"
            "Turning it back ON is supported and safe: the ``contracts-sandbox`` "
            "preflight check verifies the repo is reachable at boot and names "
            "the remedy if it is not, so this cannot silently regress to a "
            "permanently-degraded recorder again."
        ),
    )

    # Trust fleet — TrustFleetSanityLoop (spec §12.1)
    trust_fleet_sanity_interval: int = Field(
        default=600,
        ge=60,
        le=3600,
        description="Seconds between TrustFleetSanityLoop ticks (default 10m)",
    )
    loop_anomaly_issues_per_hour: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: files an escalation when any watched loop "
            "exceeds this many issues/hour (spec §12.1)."
        ),
    )
    loop_anomaly_repair_ratio: float = Field(
        default=2.0,
        ge=0.1,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: `repair_failures_total / repair_successes_total` "
            "over 24h breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_repair_min_sample: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: minimum 24h `failed` count before the "
            "repair_ratio detector escalates a zero-success (`no_successes`) "
            "loop. Below this floor the signal is too small to escalate and "
            "the detector returns `insufficient_data` (false-positive guard, "
            "issue #9458)."
        ),
    )
    loop_anomaly_tick_error_ratio: float = Field(
        default=0.2,
        ge=0.01,
        le=1.0,
        description=(
            "TrustFleetSanityLoop: `ticks_errored / ticks_total` over 24h "
            "breach threshold (spec §12.1)."
        ),
    )
    loop_anomaly_tick_error_min_sample: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: minimum 24h `ticks_total` count before the "
            "tick_error_ratio detector escalates. Below this floor the signal "
            "is too small to escalate and the detector returns "
            "`insufficient_data` (false-positive guard, issue #9811)."
        ),
    )
    loop_anomaly_staleness_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: staleness breach when an enabled loop has not "
            "ticked in > this × its interval (spec §12.1)."
        ),
    )
    loop_anomaly_cost_spike_ratio: float = Field(
        default=5.0,
        ge=1.0,
        le=100.0,
        description=(
            "TrustFleetSanityLoop: current-day cost breach when > this × "
            "30-day median (spec §12.1; reads §4.11 cost endpoint, tolerates absence)."
        ),
    )
    cost_plausibility_max_rate_multiple: float = Field(
        default=3.0,
        ge=1.0,
        le=100.0,
        description=(
            "Cost-plausibility guard K (#10775): build_cost_by_model flags a "
            "model whose effective $/token exceeds K x its peak table rate "
            "(the largest of input/output/cache-write/cache-read) as a likely "
            "per-backend usage-semantics mis-bill — the z.ai/GLM 6-8x class "
            "(#10761). A correctly billed record's effective rate is always "
            "<= peak, so any K >= 1.0 is false-positive-free on clean data; the "
            "3.0 default adds headroom for char-estimate-mixed buckets. SOFT: "
            "logs a WARNING and surfaces cost_plausibility on the row, never "
            "fails the build or alters cost."
        ),
    )
    loop_anomaly_hitl_low_severity_count: int = Field(
        default=3,
        ge=1,
        le=1000,
        description=(
            "TrustFleetSanityLoop: files ONE fleet alert when the open HITL "
            "queue holds at least this many low-severity items — issues whose "
            "diagnosed severity is P4/Housekeeping OR that carry a housekeeping "
            "label (e.g. hydraflow-memory-backlog). A backstop for the pipeline "
            "over-escalating auto-filed housekeeping into human-judgment forks "
            "(#10310). Conservatively defaulted to 3 so a single mis-scoped "
            "item never pages a human."
        ),
    )
