from pathlib import Path

import pytest
import yaml

from arch._functional_areas_schema import load_functional_areas
from arch.extractors.loops import extract_loops
from arch.extractors.ports import extract_ports

_PRE_ASSIGNED: set[str] = set()


def test_every_loop_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    assert yaml_path.exists(), "docs/arch/functional_areas.yml must be committed"

    fa = load_functional_areas(yaml_path)
    assigned: set[str] = set()
    for area in fa.areas.values():
        assigned.update(area.loops)

    discovered = {info.name for info in extract_loops(real_repo_root / "src")}
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} loops are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml and add each to the "
            "appropriate area's `loops:` list."
        )


def test_every_port_is_assigned_to_an_area(real_repo_root: Path):
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    assert yaml_path.exists(), "docs/arch/functional_areas.yml must be committed"

    fa = load_functional_areas(yaml_path)
    assigned: set[str] = set()
    for area in fa.areas.values():
        assigned.update(area.ports)

    discovered = {
        info.name
        for info in extract_ports(
            src_dir=real_repo_root / "src",
            fakes_dir=real_repo_root / "src/mockworld/fakes",
        )
    }
    missing = discovered - assigned
    if missing:
        pytest.fail(
            f"{len(missing)} ports are not assigned to any functional area:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nFix: edit docs/arch/functional_areas.yml `ports:` lists."
        )


def test_functional_areas_modules_paths_exist(real_repo_root: Path):
    """Every literal (non-glob) path in a modules: list must exist on disk.

    Glob patterns (containing '*') are exempt — they are validated at
    generation time by the extractor, not here.
    """
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    assert yaml_path.exists(), "docs/arch/functional_areas.yml must be committed"

    data = yaml.safe_load(yaml_path.read_text())
    missing: list[str] = []
    for area in data.get("areas", {}).values():
        for path in area.get("modules", []):
            if "*" in path:
                continue  # glob — skip literal-existence check
            if not (real_repo_root / path).exists():
                missing.append(path)

    assert not missing, (
        "Bad modules: paths in docs/arch/functional_areas.yml "
        "(paths that don't exist on disk):\n  " + "\n  ".join(sorted(missing))
    )


def test_no_phantom_assignments(real_repo_root: Path):
    """Loops/ports listed in the YAML but absent from code → fail."""
    yaml_path = real_repo_root / "docs/arch/functional_areas.yml"
    assert yaml_path.exists(), "docs/arch/functional_areas.yml must be committed"

    fa = load_functional_areas(yaml_path)
    discovered_loops = {info.name for info in extract_loops(real_repo_root / "src")}
    discovered_ports = {
        info.name
        for info in extract_ports(
            src_dir=real_repo_root / "src",
            fakes_dir=real_repo_root / "src/mockworld/fakes",
        )
    }

    phantom_loops: list[tuple[str, str]] = []
    phantom_ports: list[tuple[str, str]] = []
    for key, area in fa.areas.items():
        for ln in area.loops:
            if ln not in discovered_loops and ln not in _PRE_ASSIGNED:
                phantom_loops.append((key, ln))
        for pn in area.ports:
            if pn not in discovered_ports:
                phantom_ports.append((key, pn))

    if phantom_loops or phantom_ports:
        msg = []
        if phantom_loops:
            msg.append("Phantom loops (in YAML, not in code):")
            msg.extend(f"  {area}.loops: {ln}" for area, ln in phantom_loops)
        if phantom_ports:
            msg.append("Phantom ports:")
            msg.extend(f"  {area}.ports: {pn}" for area, pn in phantom_ports)
        pytest.fail(
            "\n".join(msg)
            + "\n\nFix: rename the YAML entry to match the live class name, or remove it."
        )


# ---------------------------------------------------------------------------
# workstream-fixes-over-loops ratchet (#10294 rule, #10318 enforcement)
#
# The `workstream-fixes-over-loops` memory rule (promoted in #10294, see
# docs/wiki/memory-feedback/feedback-workstream-fixes-over-loops.md) says:
# prefer fixing the workstream — an existing pipeline PHASE/step or a new
# intake/classifier on an existing loop — over minting another standalone
# caretaker loop. A new loop is not the default unit of automation.
#
# `test_new_loops_justify_workstream_alternative` gives that rule teeth as a
# SHRINK-ONLY ratchet, mirroring the disturbance-dampener block-new gate
# (tests/test_disturbance_ratchet.py): every standalone loop present when the
# ratchet was introduced is grandfathered below; a loop added afterwards must
# either be a workstream fix (zero new loops) or be registered in
# `_JUSTIFIED_NEW_LOOPS` with a one-line reason naming the host that was
# considered and rejected. The baseline only shrinks — removing a loop means
# pruning it from `_GRANDFATHERED_LOOPS` in the same change.
# ---------------------------------------------------------------------------

# Standalone `BaseBackgroundLoop` subclasses that pre-date this ratchet. They
# are accepted as-is (not retro-audited against the rule) but are frozen: no
# NEW loop may join this set — new loops go through the gate below.
_GRANDFATHERED_LOOPS: frozenset[str] = frozenset(
    {
        "ADRReviewerLoop",
        "AdrConformanceLoop",
        "AutoAgentPreflightLoop",
        "AutoTightenLoop",
        "BranchProtectionAuditorLoop",
        "CIMonitorLoop",
        "ContractRefreshLoop",
        "ConvergenceOscillationLoop",
        "CorpusLearningLoop",
        "CostBudgetWatcherLoop",
        "DependabotMergeLoop",
        "DetectorCalibrationLoop",
        "DiagnosticLoop",
        "DiagramLoop",
        "DisturbanceDampenerLoop",
        "EdgeProposerLoop",
        "EntryEvidenceLoop",
        "EpicMonitorLoop",
        "EpicSweeperLoop",
        "ErosionMetricsLoop",
        "FakeCoverageAuditorLoop",
        "FitnessScorecardLoop",
        "FlakeTrackerLoop",
        "GateActivatorLoop",
        "GateHealthLoop",
        "GitHubCacheLoop",
        "HealthMonitorLoop",
        "HumanSteeringLoop",
        "IssueRefinementLoop",
        "LabelDriftWatcherLoop",
        "LiveCorpusReplayLoop",
        "LogIngestLoop",
        "MemoryBacklogLoop",
        "MergeStateWatcherLoop",
        "PRUnstickerLoop",
        # PrRedRepairLoop: documented historical violation of the #10027
        # "zero new loops" operator steer. It was specced as an intake on
        # PRUnstickerLoop's existing CI-fix dispatch but shipped (#10124 /
        # #10157) as a full standalone loop. Grandfathered per #10318
        # (Option A): kept working and honestly recorded rather than ripped
        # out. See feedback-workstream-fixes-over-loops.md.
        "PrRedRepairLoop",
        "PricingRefreshLoop",
        "PrinciplesAuditLoop",
        "RCBudgetLoop",
        "RepoWikiLoop",
        "ReportIssueLoop",
        "RetrospectiveLoop",
        "RunsGCLoop",
        "SandboxFailureFixerLoop",
        "SecurityPatchLoop",
        "SkillPromptEvalLoop",
        "StagingBisectLoop",
        "StagingPromotionLoop",
        "StaleIssueGCLoop",
        "StaleIssueLoop",
        "TermProposerLoop",
        "TermPrunerLoop",
        "TriageRetryLoop",
        "TrustFleetSanityLoop",
        "WikiRotDetectorLoop",
        "WorkspaceGCLoop",
    }
)

# Loops added AFTER this ratchet that are legitimately standalone. Each entry
# must name, in one line, the workstream host (phase/step or existing-loop
# intake) that was considered and why it could not own the behaviour — the
# same "name the intended HOST explicitly" discipline the memory doc asks for.
# Empty is the healthy default: the first choice is always a workstream fix.
_JUSTIFIED_NEW_LOOPS: dict[str, str] = {
    # #10371: considered hosting the fail-open RATE monitor as a step in the
    # review phase's post-verify path (where the per-event ledger IS written)
    # and as an intake on DetectorCalibrationLoop. Rejected both: the Shewhart
    # control limit is a function of the WHOLE ledger across all PRs/surfaces —
    # no single PR's review phase can see the cross-PR rate — and
    # DetectorCalibrationLoop mines hitl-escalation issues, a different data
    # source. A per-tick rate monitor over the diagnostics ledger is genuinely
    # standalone cross-cutting cadence work with no natural phase/loop host.
    "FailOpenMonitorLoop": "cross-PR fail-open rate control limit; no phase sees it",
    # EscapeLedgerLoop (#10367): a standalone outer-loop falsification
    # instrument. Considered hosting it on the triage phase, but rejected — the
    # ledger spans multiple detection sources (revert/hotfix/regression-pin/
    # bug-issue git scans) and needs its own base-branch commit cursor + cadence
    # over the whole merge stream, which no single existing phase/loop observes.
    "EscapeLedgerLoop": (
        "outer-loop falsification instrument spanning multiple detection "
        "sources with its own merged-commit cursor; triage host rejected "
        "(no commit-stream cadence)"
    ),
    # InterventionTallyLoop (#10369): the attention-side twin of the escape
    # ledger — a standalone outer-loop instrument that aggregates FOUR human-
    # touch streams (steering + HITL + control-route + /hf CLI) on their own
    # event-stream cursor + cadence. Considered hosting it on HumanSteeringLoop
    # (an existing intake) and the HITL phase, but rejected — each sees only
    # ONE of the four sources, and neither observes the whole cross-cutting
    # human-load stream this trends against the shared per-100-merges denominator.
    "InterventionTallyLoop": (
        "attention-side falsification instrument aggregating 4 human-touch "
        "streams on its own event cursor; HumanSteeringLoop/HITL-phase host "
        "rejected (single source / no cross-cutting cadence)"
    ),
    # SampledAuditLoop (#10370): acceptance sampling applied to the gauntlet —
    # a governed random sample of MERGED PRs re-audited post-merge. Considered
    # hosting on the review phase and on EscapeLedgerLoop, both rejected: review
    # is pre-merge (this is strictly post-merge, by design, so a fresh context
    # sees the merged state), and the escape ledger is a MECHANICAL git scanner
    # with no LLM budget / Shewhart rate governor / per-tick sampling cadence —
    # bolting a governed LLM sampler onto it would fuse two independent
    # instruments. It cross-LINKS into the escape ledger (upheld disagreements)
    # rather than living inside it.
    "SampledAuditLoop": (
        "governed post-merge acceptance-sampling re-audit with its own LLM "
        "budget + Shewhart rate governor + merged-PR cursor; review-phase host "
        "rejected (pre-merge) and EscapeLedgerLoop host rejected (mechanical "
        "scanner, no sampling cadence) — cross-links into the ledger instead"
    ),
    # SecondOrderVitalsLoop (#10373): the capstone residual monitor computing
    # the JOINT green-while-dying condition across all four instruments. There
    # is no workstream host by construction — it is the ONLY component that
    # reads every instrument's ledger at once and correlates them; hosting it on
    # any single instrument's loop (escape/intervention/audit/independence)
    # would fuse the very signals it must keep independent, and no pipeline phase
    # sees the cross-instrument residual. It has its own per-series baseline
    # state + evaluation cadence + never-batched alarm — genuinely standalone
    # cross-cutting cadence work.
    "SecondOrderVitalsLoop": (
        "cross-instrument residual monitor correlating all 4 instrument ledgers "
        "against the primary gate; every single-instrument-loop host rejected "
        "(would fuse the independent signals) and no phase sees the joint "
        "residual — its own per-series baselines + never-batched alarm"
    ),
    # CharterDriftCaretakerLoop (#10936, #11748): periodic per-repo conformance
    # audit of each managed repo's charter.yaml. Considered hosting it as
    # an intake on BranchProtectionAuditorLoop (the sibling per-repo contract-
    # drift auditor) and as an onboarding-phase step, both rejected: branch
    # protection audits live GitHub ruleset API state on a 7-day cadence, a
    # different data source/contract from filesystem template-layer conformance
    # (fusing them couples two independent contracts), and onboarding is a
    # one-shot stamp with no recurring cadence to re-check drift. It is genuinely
    # standalone cross-cutting caretaker cadence work, mirroring the grandfathered
    # ADR-drift and branch-protection-drift loops it is modeled on (ADR-0121).
    "CharterDriftCaretakerLoop": (
        "per-repo charter.yaml conformance drift audit on its own cadence; "
        "BranchProtectionAuditorLoop-intake host rejected (different contract/data "
        "source) and onboarding-phase host rejected (one-shot, no re-check cadence)"
    ),
    # GoalSupervisorLoop (#10733, ADR-0124): the Tier-2 goal supervisor. It is a
    # cross-cutting cadence over the WHOLE-factory liveness snapshot (every
    # loop's heartbeat + credit-failover + boot-SHA + watchdog state). Considered
    # hosting it on HealthMonitorLoop (the sibling meta-observability worker) and
    # rejected: HealthMonitorLoop is the deterministic Tier-1 *mechanism*
    # repairer (restart-to-known-good, no LLM), whereas the Tier-2 supervisor is
    # a goal-driven Fable agent that reads Tier-1's signals and redirects
    # *mission* — ADR-0124 deliberately separates the two tiers (each tier is a
    # monitor, not a link). Fusing them would put an LLM in the deterministic
    # kernel. No pipeline phase observes cross-loop liveness, so it is genuinely
    # standalone cadence work.
    "GoalSupervisorLoop": (
        "Tier-2 goal supervisor over whole-factory liveness on its own cadence; "
        "HealthMonitorLoop-intake host rejected (Tier-1 deterministic mechanism "
        "repair vs Tier-2 goal-driven mission redirect — ADR-0124 keeps the tiers "
        "separate so no LLM sits in the deterministic kernel)"
    ),
    # GatewayCoverageLoop (#11473): repository-scoped attribution completeness
    # compares gateway ledger spend with all agentic telemetry on its own
    # window/cadence. CostBudgetWatcherLoop was considered and rejected because
    # it enforces budgets rather than detecting bypass; HealthMonitorLoop was
    # rejected because it repairs runtime mechanisms rather than preserving a
    # durable, auditable coverage ceiling. No individual workstream phase sees
    # every gateway and direct-provider exchange across the fleet.
    "GatewayCoverageLoop": (
        "repo-wide gateway-vs-direct attribution on its own window/cadence; "
        "CostBudgetWatcherLoop host rejected (budget enforcement, not bypass "
        "detection) and HealthMonitorLoop host rejected (runtime repair, not "
        "durable coverage-ceiling evidence)"
    ),
}


def test_new_loops_justify_workstream_alternative(real_repo_root: Path):
    """Shrink-only ratchet enforcing workstream-fixes-over-loops (#10294/#10318).

    A new standalone loop must justify why a workstream fix (an existing
    pipeline phase/step or an intake on an existing loop) could not host it,
    instead of minting another caretaker loop. Everything present when the
    ratchet landed is grandfathered in ``_GRANDFATHERED_LOOPS``; anything
    added later must be a workstream fix (no new loop) or be registered in
    ``_JUSTIFIED_NEW_LOOPS``. The baseline only shrinks.
    """
    discovered = {info.name for info in extract_loops(real_repo_root / "src")}

    allowed = _GRANDFATHERED_LOOPS | set(_JUSTIFIED_NEW_LOOPS)
    unjustified_new = discovered - allowed
    if unjustified_new:
        pytest.fail(
            f"{len(unjustified_new)} new standalone loop(s) added without a "
            "workstream-alternative justification:\n  "
            + "\n  ".join(sorted(unjustified_new))
            + "\n\nPrefer a workstream fix over a new loop (see "
            "docs/wiki/memory-feedback/feedback-workstream-fixes-over-loops.md): "
            "can an existing PHASE own it as a step/gate, or an existing loop "
            "own it as a new intake/classifier? If it is genuinely standalone "
            "cross-cutting cadence work with no natural host, add it to "
            "`_JUSTIFIED_NEW_LOOPS` in this file with a one-line reason naming "
            "the host you considered and rejected."
        )

    stale = _GRANDFATHERED_LOOPS - discovered
    if stale:
        pytest.fail(
            f"{len(stale)} grandfathered loop(s) no longer exist in code:\n  "
            + "\n  ".join(sorted(stale))
            + "\n\nThe ratchet only shrinks — prune these from "
            "`_GRANDFATHERED_LOOPS` in this file so the baseline stays honest."
        )
