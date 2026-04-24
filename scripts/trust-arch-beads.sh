#!/usr/bin/env bash
# trust-arch-beads.sh
#
# Decompose the 11 `trust-arch-hardening` implementation plans into `bd`
# (beads) issues with cross-plan dependencies.
#
# Idempotent: maintains a marker file at scripts/.beads-created-markers
# mapping "<plan_slug>:<task_id>" -> "<bead_id>". On re-run, existing
# lines are skipped (no duplicate beads created).
#
# Plans live in docs/superpowers/plans/2026-04-22-*.md in this worktree.
# Beads live in the shared hydraflow dolt database (the `bd` daemon runs
# in the primary checkout at /Users/travisf/Documents/projects/hydraflow).
# We `cd` to that checkout for each `bd` call so `bd` can locate the DB.
#
# This script is compatible with macOS default bash 3.2 — it relies on
# the markers file (not bash associative arrays) as the in-memory lookup.
#
# Usage:
#   ./scripts/trust-arch-beads.sh              # create all beads + deps
#   ./scripts/trust-arch-beads.sh --dry-run    # print what would happen
#
set -euo pipefail

WORKTREE="/Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening"
BD_CWD="/Users/travisf/Documents/projects/hydraflow"
MARKERS="${WORKTREE}/scripts/.beads-created-markers"
DRY_RUN="${1:-}"

mkdir -p "$(dirname "${MARKERS}")"
touch "${MARKERS}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# get_marker "<plan>:<task>" -> echoes stored bead id or empty.
get_marker() {
    local key="$1"
    # Use awk for exact match of the LHS token.
    awk -v k="${key}" '$1 == k && $2 == "->" { print $3; exit }' "${MARKERS}"
}

save_marker() {
    local key="$1"
    local bead_id="$2"
    echo "${key} -> ${bead_id}" >> "${MARKERS}"
}

# create_bead PLAN TASK_ID TITLE DESCRIPTION
create_bead() {
    local plan="$1"
    local task="$2"
    local title="$3"
    local desc="$4"
    local key="${plan}:${task}"

    local existing
    existing="$(get_marker "${key}")"
    if [[ -n "${existing}" ]]; then
        echo "[skip] ${key} -> ${existing}" >&2
        return 0
    fi

    if [[ "${DRY_RUN}" == "--dry-run" ]]; then
        echo "[dry-run create] ${key}  title='${title}'" >&2
        save_marker "${key}" "DRY-RUN-${plan}-${task}"
        return 0
    fi

    local bead_id
    bead_id="$(cd "${BD_CWD}" && bd create --silent -t feature \
        --title "${title}" \
        -d "${desc}" 2>&1 | tail -n1)"

    if [[ -z "${bead_id}" || ! "${bead_id}" =~ ^hydraflow-[a-z0-9]+$ ]]; then
        echo "[error] bd create failed for ${key}: '${bead_id}'" >&2
        exit 1
    fi

    save_marker "${key}" "${bead_id}"
    echo "[create] ${key} -> ${bead_id}" >&2
}

# lookup PLAN:TASK — echoes bead id or exits non-zero.
lookup() {
    local key="$1"
    local id
    id="$(get_marker "${key}")"
    if [[ -z "${id}" ]]; then
        echo "[error] no marker for ${key}" >&2
        return 1
    fi
    echo "${id}"
}

# add_dep CHILD_BEAD PARENT_BEAD [TAG]
# `bd link <child> <parent>` means parent blocks child.
add_dep() {
    local child="$1"
    local parent="$2"
    local tag="${3:-dep}"

    if [[ -z "${child}" || -z "${parent}" ]]; then
        echo "[skip dep] empty id (child='${child}' parent='${parent}')" >&2
        return 0
    fi
    if [[ "${child}" == DRY-RUN-* || "${parent}" == DRY-RUN-* ]]; then
        echo "[dry-run dep] ${parent} blocks ${child} (${tag})" >&2
        return 0
    fi

    local depkey="dep:${child}<-${parent}"
    if grep -qxF "${depkey}" "${MARKERS}"; then
        echo "[skip dep] ${depkey}" >&2
        return 0
    fi

    if ! (cd "${BD_CWD}" && bd link "${child}" "${parent}" --type blocks) >/dev/null 2>&1; then
        echo "[warn] bd link ${child} ${parent} failed (may already exist)" >&2
    fi
    echo "${depkey}" >> "${MARKERS}"
    echo "[dep] ${parent} blocks ${child} (${tag})" >&2
}

fmt_title() {
    local slug="$1"
    local task="$2"
    shift 2
    echo "[${slug}] Task ${task}: $*"
}

plan_path() {
    case "$1" in
        adv)        echo "docs/superpowers/plans/2026-04-22-adversarial-skill-corpus.md" ;;
        contracts)  echo "docs/superpowers/plans/2026-04-22-fake-contract-tests.md" ;;
        bisect)     echo "docs/superpowers/plans/2026-04-22-staging-red-attribution-bisect.md" ;;
        audit)      echo "docs/superpowers/plans/2026-04-22-principles-audit-loop.md" ;;
        fleet1)     echo "docs/superpowers/plans/2026-04-22-caretaker-fleet-part-1.md" ;;
        rc-budget)  echo "docs/superpowers/plans/2026-04-22-rc-budget-loop.md" ;;
        wiki-rot)   echo "docs/superpowers/plans/2026-04-22-wiki-rot-detector-loop.md" ;;
        sanity)     echo "docs/superpowers/plans/2026-04-22-trust-fleet-sanity-loop.md" ;;
        product)    echo "docs/superpowers/plans/2026-04-22-product-phase-trust.md" ;;
        waterfall)  echo "docs/superpowers/plans/2026-04-22-cost-waterfall-helper.md" ;;
        rollups)    echo "docs/superpowers/plans/2026-04-22-cost-rollups-and-fleet-ui.md" ;;
        *) echo "docs/superpowers/plans/UNKNOWN.md" ;;
    esac
}

mkdesc() {
    local slug="$1"
    local taskref="$2"
    local path
    path="$(plan_path "${slug}")"
    echo "Implement per plan task ${taskref} in ${path}. See the plan for exact file paths, code, and test commands."
}

# mk PLAN TASK "TITLE"
# Short wrapper around create_bead that auto-generates title and description.
mk() {
    local plan="$1"
    local task="$2"
    local title="$3"
    create_bead "${plan}" "${task}" \
        "$(fmt_title "${plan}" "${task}" "${title}")" \
        "$(mkdesc "${plan}" "${task}")"
}

# chain_plan PLAN TASK_LIST_VAR ...
# Wire N+1 blocks-on N for every consecutive pair of tasks listed as
# positional args after the plan slug.
chain_plan() {
    local plan="$1"
    shift
    local prev=""
    local task
    for task in "$@"; do
        local cur
        cur="$(lookup "${plan}:${task}" || echo "")"
        if [[ -n "${prev}" && -n "${cur}" ]]; then
            add_dep "${cur}" "${prev}" "seq ${plan}"
        fi
        prev="${cur}"
    done
}

# ---------------------------------------------------------------------------
# Plan: adv (adversarial-skill-corpus) — 19 tasks
# Phase 1 = Tasks 1..8, Phase 2 = Tasks 9..19
# ---------------------------------------------------------------------------
mk adv 1  "Scaffold tests/trust/adversarial/ directory tree"
mk adv 2  "Implement the adversarial corpus harness"
mk adv 3  "Unit-test the harness against synthetic cases"
mk adv 4a "Seed cases 1-5 (diff-sanity bug classes)"
mk adv 4b "Seed cases 6-10 (scope-check + plan-compliance bug classes)"
mk adv 4c "Seed cases 11-15 (test-adequacy bug classes)"
mk adv 4d "Seed cases 16-20 (cross-skill + benign sentinel + hardened edges)"
mk adv 5  "Add make trust-adversarial and make trust targets"
mk adv 6  "Add trust job to rc-promotion-scenario.yml (live-LLM default)"
mk adv 7  "Smoke-test the gate end-to-end locally"
mk adv 8  "Open the Phase 1 PR"
mk adv 9  "Create the CorpusLearningLoop skeleton"
mk adv 10 "Unit-test the loop skeleton"
mk adv 11 "Implement the escape-signal reader"
mk adv 12 "Implement in-process case synthesis"
mk adv 13 "Implement the three-gate self-validation"
mk adv 14 "Wire synthesis + validation + PR opening into _do_work"
mk adv 15 "Five-checkpoint wiring (incl. telemetry emission)"
mk adv 16 "Integration test — end-to-end mocked escape -> PR"
mk adv 17 "Verify test_loop_wiring_completeness.py picks up the new loop"
mk adv 18 "MockWorld scenario — escape issue -> case PR against staging"
mk adv 19 "Run full quality gate and open the Phase 2 PR"

chain_plan adv 1 2 3 4a 4b 4c 4d 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19

# ---------------------------------------------------------------------------
# Plan: contracts (fake-contract-tests) — Tasks 0-24 (25 tasks)
# ---------------------------------------------------------------------------
mk contracts 0   "Manual pre-requisite — create sandbox repo"
mk contracts 1   "Scaffold tests/trust/contracts/ tree"
mk contracts 2   "Cassette schema + normalizer registry"
mk contracts 3   "Unit-test the cassette schema"
mk contracts 4   "Replay harness helper"
mk contracts 5   "Unit-test the replay harness"
mk contracts 6   "test_fake_github_contract.py + seed cassettes"
mk contracts 7   "test_fake_git_contract.py + fixture repo"
mk contracts 8   "test_fake_docker_contract.py + seed cassettes"
mk contracts 9   "test_fake_llm_contract.py + stream samples"
mk contracts 10  "make trust-contracts target + extend make trust + CI"
mk contracts 11  "ContractRefreshLoop skeleton"
mk contracts 12  "Unit-test loop construction + tick callability"
mk contracts 13  "Recording subroutines — real gh/git/docker/claude"
mk contracts 14  "Diff detection against committed cassettes"
mk contracts 15  "Refresh PR via open_automated_pr_async"
mk contracts 16  "Replay-gate post-refresh + file fake-drift companion issue"
mk contracts 17  "Stream-protocol drift handling"
mk contracts 18  "Per-adapter 3-attempt escalation tracker"
mk contracts 19a "Five-checkpoint wiring — service_registry.py"
mk contracts 19b "Five-checkpoint wiring — orchestrator.py"
mk contracts 19c "Five-checkpoint wiring — ui/src/constants.js"
mk contracts 19d "Five-checkpoint wiring — _INTERVAL_BOUNDS"
mk contracts 19e "Five-checkpoint wiring — config.py"
mk contracts 20  "Per-loop telemetry emission"
mk contracts 21  "Integration test — end-to-end mocked drift"
mk contracts 22  "Extend test_loop_wiring_completeness.py"
mk contracts 23  "MockWorld scenario — ContractRefreshLoop end-to-end"
mk contracts 24  "Final quality gate + PR description"

chain_plan contracts 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19a 19b 19c 19d 19e 20 21 22 23 24

# ---------------------------------------------------------------------------
# Plan: bisect (staging-red-attribution-bisect) — Tasks 1-27
# ---------------------------------------------------------------------------
mk bisect 1  "Add six new fields to StateData"
mk bisect 2  "Add StagingBisectStateMixin with getters/setters"
mk bisect 3  "Write state on the promoted path in StagingPromotionLoop"
mk bisect 4  "Write state on the ci_failed path in StagingPromotionLoop"
mk bisect 5  "Wire state kwarg through service_registry"
mk bisect 6  "Add make bisect-probe target"
mk bisect 7  "Add three config fields"
mk bisect 8  "StagingBisectLoop skeleton with tick-time detection"
mk bisect 9  "Persist _last_processed_rc_red_sha via DedupStore"
mk bisect 10 "Flake filter"
mk bisect 11 "Bisect harness — worktree setup + git bisect run"
mk bisect 12 "Attribution — resolve first-bad SHA to its PR number"
mk bisect 13 "Safety guardrail — block second revert in one cycle"
mk bisect 14 "Revert PR creation"
mk bisect 15 "Retry issue filing"
mk bisect 16 "Outcome watchdog"
mk bisect 17 "Wire pipeline — _run_full_bisect_pipeline"
mk bisect 18 "Edge — invalid bisect range skips cleanly"
mk bisect 19 "Five-checkpoint wiring — ServiceRegistry + build_services"
mk bisect 20 "Five-checkpoint wiring — orchestrator"
mk bisect 21 "Five-checkpoint wiring — UI constants"
mk bisect 22 "Five-checkpoint wiring — route bounds"
mk bisect 23 "Telemetry emission — subprocess traces for StagingBisectLoop"
mk bisect 24 "E2E — three-commit fixture repo"
mk bisect 25 "Verify the loop-wiring completeness test accepts StagingBisectLoop"
mk bisect 26 "MockWorld scenario — StagingBisectLoop end-to-end through fakes"
mk bisect 27 "PR description + final commit"

chain_plan bisect 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27

# ---------------------------------------------------------------------------
# Plan: audit (principles-audit-loop) — Tasks 0-22 (23 tasks)
# Note: some tasks marked "merged into X" in the plan; kept as beads so
# plan references remain stable and implementers can find them.
# ---------------------------------------------------------------------------
mk audit 0  "Benchmark make audit runtime, decide CI placement"
mk audit 1  "Add ManagedRepo config model + managed_repos field + JSON env override"
mk audit 2  "Config model test (merged into Task 1)"
mk audit 3  "Add managed_repos_onboarding_status + last_green_audit + principles_drift_attempts to StateData"
mk audit 4  "Add PrinciplesAuditStateMixin with accessors"
mk audit 5  "Orchestrator skips blocked repos in pipeline dispatch"
mk audit 6  "Orchestrator block-skip test (merged into Task 5)"
mk audit 7  "PrinciplesAuditLoop skeleton"
mk audit 8  "Skeleton test (merged into Task 7)"
mk audit 9  "HydraFlow-self audit + snapshot save"
mk audit 10 "Managed-repo shallow checkout + audit"
mk audit 11 "Pass/fail diff + check-type branching"
mk audit 12 "Issue filing + severity-based escalation"
mk audit 13 "Diff + filing integration test (merged into Tasks 11-12)"
mk audit 14 "Onboarding detection + initial audit"
mk audit 15 "Onboarding ready-on-green flow + full _do_work assembly"
mk audit 16 "Onboarding transition tests (covered by Tasks 14-15)"
mk audit 17 "Add audit job to CI workflow"
mk audit 18 "Telemetry instrumentation (stub emit_loop_subprocess_trace if absent)"
mk audit 19 "Five-checkpoint wiring"
mk audit 20 "test_loop_wiring_completeness.py verification (covered by Step 19.5)"
mk audit 21 "MockWorld scenario — onboarding-blocked + drift-regression"
mk audit 22 "Final PR"

chain_plan audit 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22

# ---------------------------------------------------------------------------
# Plan: fleet1 (caretaker-fleet-part-1) — F0-F8, S1-S7, C1-C7 (23 tasks)
# Phase 1 = F tasks (FlakeTrackerLoop)
# Phase 2 = S tasks (SkillPromptEvalLoop) — depends on adv Phase 1
# Phase 3 = C tasks (FakeCoverageAuditorLoop) — depends on contracts Phase 1
# ---------------------------------------------------------------------------
mk fleet1 F0 "Verify RC workflow emits JUnit XML; add upload step if missing"
mk fleet1 F1 "Add flake-tracker state fields + mixin"
mk fleet1 F2 "Add flake_tracker_interval + flake_threshold config + env override"
mk fleet1 F3 "FlakeTrackerLoop skeleton + JUnit parsing helper (lazy telemetry import)"
mk fleet1 F4 "RC artifact downloader + tick logic"
mk fleet1 F5 "Escalation + dedup-close reconcile tests"
mk fleet1 F6 "Five-checkpoint wiring for flake_tracker"
mk fleet1 F7 "MockWorld scenario — flaky test detected across 20 runs"
mk fleet1 F8 "Phase 1 close-out — make quality and intermediate push"
mk fleet1 S1 "Add skill_prompt_eval_interval config + env override"
mk fleet1 S2 "Add skill-prompt state mixin"
mk fleet1 S3 "SkillPromptEvalLoop skeleton + dual-role tick (lazy telemetry import)"
mk fleet1 S4 "Escalation test + close-reconcile test"
mk fleet1 S5 "Five-checkpoint wiring for skill_prompt_eval"
mk fleet1 S6 "MockWorld scenario — corpus drift + weak-case sampling"
mk fleet1 S7 "Phase 2 close-out — quality gate"
mk fleet1 C1 "Add fake_coverage_auditor_interval config + env override"
mk fleet1 C2 "Add fake-coverage state mixin"
mk fleet1 C3 "FakeCoverageAuditorLoop + AST introspection helpers (lazy telemetry import)"
mk fleet1 C4 "Tick behavior test — gap filing + subtype labels"
mk fleet1 C5 "Five-checkpoint wiring for fake_coverage_auditor"
mk fleet1 C6 "MockWorld scenario — uncovered adapter + helper"
mk fleet1 C7 "Phase 3 close-out — quality gate + PR"

chain_plan fleet1 F0 F1 F2 F3 F4 F5 F6 F7 F8 S1 S2 S3 S4 S5 S6 S7 C1 C2 C3 C4 C5 C6 C7

# ---------------------------------------------------------------------------
# Plan: rc-budget — Tasks 1-10
# ---------------------------------------------------------------------------
mk rc-budget 1  "State schema for duration history"
mk rc-budget 2  "Config fields + env overrides"
mk rc-budget 3  "Loop skeleton + tick stub (lazy telemetry import)"
mk rc-budget 4  "Fetcher + baseline computation"
mk rc-budget 5  "Signal check, filing, escalation, reconcile"
mk rc-budget 6  "Kill-switch + both-signal integration tests"
mk rc-budget 7  "Five-checkpoint wiring"
mk rc-budget 8  "Loop-wiring-completeness confirmation"
mk rc-budget 9  "MockWorld scenario"
mk rc-budget 10 "Final verification + PR"

chain_plan rc-budget 1 2 3 4 5 6 7 8 9 10

# ---------------------------------------------------------------------------
# Plan: wiki-rot — Tasks 1-10
# ---------------------------------------------------------------------------
mk wiki-rot 1  "State schema for per-cite repair attempts"
mk wiki-rot 2  "Config field + env override"
mk wiki-rot 3  "Cite-extraction helper"
mk wiki-rot 4  "Loop skeleton + per-repo tick stub"
mk wiki-rot 5  "Per-repo tick: load wiki, extract cites, verify, file issues, escalate"
mk wiki-rot 6  "Close-reconcile (dedup/attempt clearance on escalation close)"
mk wiki-rot 7  "Lazy trace emission + kill-switch coverage"
mk wiki-rot 8  "Five-checkpoint wiring"
mk wiki-rot 9  "Loop-wiring-completeness confirmation + catalog update"
mk wiki-rot 10 "MockWorld scenario + final verification + PR"

chain_plan wiki-rot 1 2 3 4 5 6 7 8 9 10

# ---------------------------------------------------------------------------
# Plan: sanity (trust-fleet-sanity-loop) — Tasks 1-13
# ---------------------------------------------------------------------------
mk sanity 1  "State schema (per-anomaly attempts + last-run + counter snapshots)"
mk sanity 2  "Config fields + env overrides"
mk sanity 3  "Loop skeleton + tick stub (lazy telemetry import)"
mk sanity 4  "Metrics-reader helpers (event log, heartbeats, lazy cost-reader)"
mk sanity 5  "Five anomaly detectors (pure functions in a helper module)"
mk sanity 6  "Filing + 1-attempt escalation + close-reconcile"
mk sanity 7  "HealthMonitor dead-man-switch integration"
mk sanity 8  "Kill-switch integration test"
mk sanity 9  "/api/trust/fleet endpoint schema documentation"
mk sanity 10 "Five-checkpoint wiring"
mk sanity 11 "Loop-wiring-completeness confirmation"
mk sanity 12 "MockWorld scenario + catalog"
mk sanity 13 "Final verification + PR"

chain_plan sanity 1 2 3 4 5 6 7 8 9 10 11 12 13

# ---------------------------------------------------------------------------
# Plan: product (product-phase-trust) — Tasks 1-16
# Phase 1 = 1..3, Phase 2 = 4..6, Phase 3 = 7..11, Phase 4 = 12..14, Phase 5 = 15..16.
# ---------------------------------------------------------------------------
mk product 1  "Create src/discover_completeness.py"
mk product 2  "Unit-test discover-completeness"
mk product 3  "Register discover-completeness in BUILTIN_SKILLS"
mk product 4  "Create src/shape_coherence.py"
mk product 5  "Unit-test shape-coherence"
mk product 6  "Register shape-coherence in BUILTIN_SKILLS"
mk product 7  "Add max_discover_attempts / max_shape_attempts to HydraFlowConfig"
mk product 8  "Extend DiscoverRunner with evaluator dispatch + retry + escalation"
mk product 9  "Extend ShapeRunner with evaluator dispatch + retry + escalation"
mk product 10 "Unit-test DiscoverRunner evaluator dispatch"
mk product 11 "Unit-test ShapeRunner evaluator dispatch"
mk product 12 "Seed 4 Discover cases"
mk product 13 "Seed 4 Shape cases"
mk product 14 "Verify the harness accepts the new cases unchanged"
mk product 15 "MockWorld scenario — vague issue -> Discover (bad->good) -> Shape -> Plan"
mk product 16 "Open the PR"

chain_plan product 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16

# ---------------------------------------------------------------------------
# Plan: waterfall (cost-waterfall-helper) — Tasks 1-4
# Task 1 = the emit_loop_subprocess_trace helper that every loop telemetry
# task depends on.
# ---------------------------------------------------------------------------
mk waterfall 1 "Module-level helper in trace_collector.py (emit_loop_subprocess_trace)"
mk waterfall 2 "Phase-action aggregator module"
mk waterfall 3 "Route wiring in _diagnostics_routes.py"
mk waterfall 4 "Quality gate + PR"

chain_plan waterfall 1 2 3 4

# ---------------------------------------------------------------------------
# Plan: rollups (cost-rollups-and-fleet-ui) — Tasks 1-17
# ---------------------------------------------------------------------------
mk rollups 1  "Shared aggregator helper _cost_rollups.py"
mk rollups 2  "/api/diagnostics/cost/rolling-24h route"
mk rollups 3  "/api/diagnostics/cost/top-issues route"
mk rollups 4  "/api/diagnostics/cost/by-loop route"
mk rollups 5  "/api/diagnostics/loops/cost route (machinery-level dashboard)"
mk rollups 6  "Event-based metric reader + fleet route (/api/trust/fleet)"
mk rollups 7  "Config fields + env overrides"
mk rollups 8  "Alert helper module cost_budget_alerts.py"
mk rollups 9  "Daily-budget hook in report_issue_loop.py"
mk rollups 10 "Per-issue-cost hook in pr_manager.py"
mk rollups 11 "FactoryCostSummary.jsx (top-line KPIs)"
mk rollups 12 "PerLoopCostTable.jsx (sortable + sparkline + 2x highlight)"
mk rollups 13 "WaterfallView.jsx (consumes Plan 6b-1 endpoint)"
mk rollups 14 "FactoryCostTab.jsx integration + wire into DiagnosticsTab"
mk rollups 15 "UI snapshot tests (sanity check)"
mk rollups 16 "End-to-end scenario test_diagnostics_waterfall_scenario.py"
mk rollups 17 "Quality gate, tree walk, and PR"

chain_plan rollups 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17

# ---------------------------------------------------------------------------
# Cross-plan dependencies
# ---------------------------------------------------------------------------

WATERFALL_T1="$(lookup 'waterfall:1')"

# 1. Every loop plan's telemetry task blocks on [waterfall] Task 1.
add_dep "$(lookup 'adv:15')"       "${WATERFALL_T1}" "telemetry adv->waterfall"
add_dep "$(lookup 'audit:18')"     "${WATERFALL_T1}" "telemetry audit->waterfall"
add_dep "$(lookup 'bisect:23')"    "${WATERFALL_T1}" "telemetry bisect->waterfall"
add_dep "$(lookup 'contracts:20')" "${WATERFALL_T1}" "telemetry contracts->waterfall"
add_dep "$(lookup 'wiki-rot:7')"   "${WATERFALL_T1}" "telemetry wiki-rot->waterfall"
add_dep "$(lookup 'rc-budget:3')"  "${WATERFALL_T1}" "telemetry rc-budget->waterfall"
add_dep "$(lookup 'sanity:3')"     "${WATERFALL_T1}" "telemetry sanity->waterfall"
add_dep "$(lookup 'fleet1:F3')"    "${WATERFALL_T1}" "telemetry fleet1-flake->waterfall"
add_dep "$(lookup 'fleet1:S3')"    "${WATERFALL_T1}" "telemetry fleet1-skill->waterfall"
add_dep "$(lookup 'fleet1:C3')"    "${WATERFALL_T1}" "telemetry fleet1-fake->waterfall"

# 2. [rollups] Task 6 depends on [sanity] completion (sanity Task 13 = final PR).
add_dep "$(lookup 'rollups:6')" "$(lookup 'sanity:13')" "rollups-fleet->sanity-done"

# 3. [fleet1] Phase 2 (S1) blocks on [adv] Phase 1 completion (adv Task 8 = Phase 1 PR).
add_dep "$(lookup 'fleet1:S1')" "$(lookup 'adv:8')" "fleet1-skill->adv-phase1"

# 4. [fleet1] Phase 3 (C1) blocks on [contracts] Phase 1 cassette infra
#    (contracts Task 10 = make trust-contracts target lands).
add_dep "$(lookup 'fleet1:C1')" "$(lookup 'contracts:10')" "fleet1-fake->contracts-phase1"

# 5. [product] Phase 3 (intra-plan) — runner extensions require the two
#    registration tasks to have landed first.
add_dep "$(lookup 'product:8')" "$(lookup 'product:3')" "product-runner->discover-registered"
add_dep "$(lookup 'product:9')" "$(lookup 'product:6')" "product-runner->shape-registered"

echo ""
echo "=== Bead creation + wiring complete ==="
echo "Markers file: ${MARKERS}"
