# Flows inventory + migration map (P0.5 of epic #10682)

**Status:** analysis (2026-07-26). **Scope:** read-only inventory. No code changes.
**Inputs:** design proposal `docs/proposals/in-framework-flows-for-workers-and-phases.md`, [ADR-0111](../adr/0111-in-framework-flow-dag-runtime.md) (the P0 primitive `src/flows/`), epic #10682.

## Purpose

P0 shipped the flow primitive (`src/flows/flow.py`: `Node` / `Edge` / `Flow` / `FlowResult`). This doc maps **every** background worker and **every** pipeline-phase step to a flow decision so that P1–P4 execute against a data-driven map instead of re-deriving per-target analysis. Every classification below is grounded in a `file:line` citation from the actual code as of `origin/staging` (`43b060c17`).

### The P0 primitive this maps onto (recap)

- `Node(name, run, kind)` — `run(state) -> state` is async; `kind ∈ {"step","gate","loop"}` is descriptive metadata (routing is always by edges). `src/flows/flow.py:70-84`.
- `Edge(src, dst, when=None)` — first-match-wins in declaration order; a `None` guard is unconditional. `src/flows/flow.py:87-98`.
- `Flow(nodes, edges, entry, on_node=, checkpoint=, kill_switch=, max_steps=)` — walks entry→edges, fires `on_node` (event bus) + `checkpoint` (persistence, ADR-0021) after each node, fail-closed on node exception and on an unroutable gate, halts observably on `kill_switch`. `src/flows/flow.py:118-270`.
- `FlowState = dict[str, Any]` — deliberately a plain dict; no bespoke schema per phase. `src/flows/flow.py:43`.

**A worker/phase is a flow candidate only if its per-tick core runs ≥2 distinct reasoning/verification stages.** A single input→output LLM call gains nothing from a DAG — the wrapper would be pure ceremony (ADR-0111 non-goals).

---

## 0. Executive summary

| Bucket | Count | Meaning |
|---|---|---|
| `multi-step-with-verification` (flow candidate) | **6 loops** + **4 phases** | ≥2 distinct reasoning/verification stages; convert to a flow. |
| `one-shot-transform` (keep as prompt) | **11 loops** + **6 of 7 dials** | one LLM call in→out; a flow is ceremony. |
| `already-loop/gate` (control already explicit / no LLM) | **49 loops** | deterministic control or an already-explicit loop; low/zero conversion value. |
| **Total loop files** | **66** | 64 registered `BaseBackgroundLoop`s + `base_background_loop` (framework base) + `adversarial_retry_loop` (helper). |

Only **6 of 66** background loops are worth converting, and **the four pipeline phases are the real prize** — they are where the multi-step reasoning, the thrash (#10659), and the reusable councils/gates live. The 7 provider dials are one-shot by design **except `adr_review`, which is already a multi-agent council** (a discrepancy with the epic's "keep as prompt" list — see §5).

**Top-5 shared nodes** (build once, reuse across phases): `convergence-gate`, `adversarial-review`, `spec-compliance-verify`, `touchpoint-expand`, `injection-screen`. All five already exist as extractable modules today (§3).

**Recommended migration order:** (1) wiki-compilation *(P1 proof, low blast radius)* → (2) **implement** *(P2, highest value — the thrash)* → (3) plan → (4) review → (5) triage. `diagnostic_loop` is the best "second worker" proof after wiki (§4).

---

## 1. Worker inventory + classification

### 1a. Background loops (66 files)

Legend: **FLOW** = `multi-step-with-verification`, **PROMPT** = `one-shot-transform`, **CTRL** = `already-loop/gate`.

#### FLOW candidates (6)

| Loop | Stages (why it's multi-step) | Evidence |
|---|---|---|
| `repo_wiki_loop` | synthesize topic → detect semantic drift → generalize-pair judge (3 LLM stages) | `repo_wiki_loop.py:375` `compile_topic`, `:572` `scan_semantic_drift`, `:108` `generalize_pair` |
| `diagnostic_loop` | Stage-1 `diagnose()` → gate → Stage-2 `fix()` | `diagnostic_loop.py:243` `_runner.diagnose()`, `:364` `_runner.fix()` |
| `adr_reviewer_loop` | pre-validation gate → multi-judge council → deliberate → synthesize | `adr_reviewer_loop.py:36` → `adr_reviewer.py:198` `_run_council_session`, `:178` gate |
| `issue_refinement_loop` | dup-judgment LLM → priority-scoring LLM (two distinct stages/tick) | `issue_refinement_loop.py:296`, `:345` |
| `skill_prompt_eval_loop` | refine → tripwire-check → holdout-validate → PR (conditional refine path) | `skill_prompt_eval_loop.py:811` `_refine_llm_complete`, `:818` `check_tripwires`, `:878` `_validate_candidate` |
| `pr_unsticker_loop` | classify cause (gate) → cause-specific resolver agent → post-fix reflection → sequential merge | `pr_unsticker.py:152` `unstick`, `:304` `_process_item`, `:801` `_reflect_on_fix` |

Note on strength: `repo_wiki_loop` and `skill_prompt_eval_loop` are *orchestrators* whose multi-step character lives in a conditional heal/refine path, not the dominant tick body — lower-value flow candidates than `diagnostic_loop`/`adr_reviewer_loop`/`issue_refinement_loop` (a clean 2–3 stage pipeline over one input each).

#### PROMPT — keep as one-shot (11)

| Loop | The single in-tick LLM stage (everything else is deterministic) | Evidence |
|---|---|---|
| `adr_drift_resolver_loop` | one `triage.classify(ctx)` per candidate → deterministic resolve/relabel/escalate | `adr_drift_resolver_loop.py:390` |
| `term_proposer_loop` | one `llm.draft(ctx)`; `validate_draft` is deterministic | `term_proposer_loop.py:258`, `:283` |
| `sampled_audit_loop` | one adversarial re-audit call → parse verdict | `sampled_audit_loop.py:376` `_audit(prompt)`, `:383` |
| `sentry_loop` | one `/hf.issue` agent maps a Sentry error → GitHub issue | `sentry_loop.py:232` |
| `pr_red_repair_loop` | one auto-agent dispatch on real red; flake gate is deterministic | `pr_red_repair_loop.py:695`, gate `:445`/`:490` |
| `sandbox_failure_fixer_loop` | one attempt-capped auto-agent fix dispatch | `sandbox_failure_fixer_loop.py:168` |
| `report_issue_loop` | one agent call bug-report→issue; `_verify_issue` is deterministic gh fixup | `report_issue_loop.py:376`, `:409` |
| `auto_agent_preflight_loop` | one preflight-agent dispatch wrapped in deterministic budget/redrive gates | `auto_agent_preflight_loop.py:597`, `:616` |
| `disturbance_dampener_loop` | one coding-agent fix + PR per unit; ratchet verify lives in CI | `disturbance_dampener_loop.py:132` `_fix_unit`, `:158` |
| `entry_evidence_loop` | one `complete_structured` mapping entry→term IDs | `entry_evidence_loop.py:304` |
| `intervention_tally_loop` | deterministic classify + one bounded cheap-LLM free-text classification | `intervention_tally_loop.py:196`, `:242` |

#### CTRL — already-loop/gate, no conversion value (49)

These invoke **no LLM** (deterministic detection/rollup/git/GC/watcher/budget control) *or* are already an explicit loop/gate in code. Splitting them into flow nodes buys nothing.

*No-LLM detectors / rollups / auditors that file findings (17):* `wiki_rot_detector_loop` (AST cite verify, `:187`), `adr_conformance_loop` (test-runner port, `:436`), `adr_touchpoint_auditor_loop` (`:706`), `term_pruner_loop` (`:83`), `edge_proposer_loop` (`:212` "No LLM call"), `contract_refresh_loop` (`:850`), `corpus_learning_loop` (template parse, `:334`), `principles_audit_loop` (`make audit-json`, `:212`), `fake_coverage_auditor_loop` (`:583`), `escape_ledger_loop` (`:297`), `erosion_metrics_loop` (`:212`), `log_ingest_loop` (LLM-free clustering, `:411`), `branch_protection_auditor_loop` (`:89`), `security_patch_loop` (`:113`), `detector_calibration_loop` (`:152`), `gate_health_loop` (`:366`), `flake_tracker_loop` (`:464`).

*Explicit-loop/gate control (already decomposed) (6):* `adversarial_retry_loop` (`run_with_metrics` critic→retry→oscillation, `:142`/`:193`), `convergence_oscillation_loop` (`:127`, docstring "NO LLM calls"), `gate_activator_loop` (`:134`), `triage_retry_loop` (relabel/backoff re-dispatch, `:206`), `staging_bisect_loop` (git bisect+revert, `:230`), `trust_fleet_sanity_loop` (`:260`).

*Deterministic GC / watcher / cache / budget / merge / promotion (17):* `ci_monitor_loop`, `merge_state_watcher_loop`, `github_cache_loop`, `runs_gc_loop`, `workspace_gc_loop`, `stale_issue_gc_loop`, `stale_issue_loop`, `label_drift_watcher_loop`, `dependabot_merge_loop`, `staging_promotion_loop`, `rc_budget_loop`, `cost_budget_watcher_loop`, `pricing_refresh_loop`, `fail_open_monitor_loop`, `epic_monitor_loop`, `epic_sweeper_loop`, `health_monitor_loop` (metric rollups + restart actuators, `:542`/`:556`).

*Measurement/instrument family (read-only-ish sensors) (7):* `second_order_vitals_loop` (`:179`), `fitness_scorecard_loop` (snapshots+event only, `:92`), `retrospective_loop` (threshold pattern detect, `retrospective.py:264`), `live_corpus_replay_loop` (fake-vs-recorded drift, `:175`), `memory_backlog_loop` (`:143`), `human_steering_loop` (directive parse, `:79`), `diagram_loop` (AST regen, `:116`).

*Framework, not a worker (2):* `base_background_loop` (abstract base), `auto_tighten_loop` (ratchet SPC control, `:160`).

**Pattern-B read-only instruments:** strictly read-only (no mutating action) are only `intervention_tally_loop` and `fitness_scorecard_loop` — they write a ledger/snapshot + emit an event and file nothing. The broader sensor family (`escape_ledger`, `second_order_vitals`, `erosion_metrics`, `sampled_audit`, `gate_health`, `flake_tracker`, `detector_calibration`, `convergence_oscillation`) *measures* but also files/escalates GitHub issues, so it is not strictly Pattern-B. Either way, **none of the instrument family needs a flow** — a sensor is a single detect→report transform.

### 1b. The 7 one-shot provider dials (`_MAINTENANCE_ROLES`, `config.py:5820-5828`)

Each dial routes tool/model/provider for one maintenance role. Mapping each to its actual runner:

| Dial | Runner (`file:function`) | Verdict | Note |
|---|---|---|---|
| `wiki_compilation` | `wiki_compiler.py:547` `WikiCompiler.compile_topic` → `:586` `_call_model` | one-shot | Single synthesize call; the **loop** around it (`repo_wiki_loop`) is the flow candidate — the dial is the `synthesize` node. |
| `term_proposer` | `term_proposer_runtime.py:65` `complete_structured` (`term_proposer_llm.py:166` `draft`) | one-shot | Exactly one spawn per draft. |
| `adr_review` | `adr_reviewer.py:327` `_run_council_session` (3 judges × ≤3 rounds) | **multi-step** | **Discrepancy:** epic lists `adr_review` as keep-as-prompt, but it is a council. See §5. |
| `transcript_summary` | `transcript_summarizer.py:283` `_call_model` | one-shot | Single summarization spawn. |
| `triage_honeypot` | `triage_honeypot.py:232` `screen_issue` | one-shot | Single screen call → deterministic tool-call/injection detection. Reused as a shared node (§3). |
| `pr_unstick` | `pr_unsticker.py:801` `_reflect_on_fix` | one-shot (dial scope only) | The dial governs only post-fix reflection; the overall `unstick()` is multi-step (see 1a). |
| `adr_drift_resolver` | `adr_drift_resolver_runtime.py:66` `complete_structured` | one-shot | Single triage classification spawn. |

---

## 2. Pipeline-phase step decomposition

Each phase is the real target: it already contains an implicit DAG. Below is the ordered step list from the live code, then the `Node`→`Edge` sketch on the P0 primitive. Nodes tagged **[SHARED: name]** should reuse a §3 shared node rather than a bespoke copy.

### 2a. triage — `TriagePhase.triage_issues` (`triage_phase.py:155`)

Per-issue pipeline: `_triage_single` (`:250`) → `_triage_single_traced` (`:322`).

Ordered steps (one issue):
1. **duplicate-close** [gate] — `_close_if_duplicate` (`:188-207`): same-title open issue → close, early-out.
2. **adr-triage** [gate] — `_triage_adr` (`:209-248`): ADR-titled → dup-close / park / route ready.
3. **stale-auditor-autoclose** [gate] — inline (`:260-284`): stale auditor finding → close.
4. **classify-issue** [llm] — `self._triage.evaluate(issue)` (`:325`, impl `triage.py:91`): length pre-filter → **injection-screen** → `_evaluate_with_llm` (`triage.py:404`). Infra failure → park + hand to `TriageRetryLoop` (`:326-352`).
   - **injection-screen** [gate] **[SHARED: injection-screen]** — `triage.py:199` → `triage_honeypot.screen_issue` (`triage_honeypot.py:232`). Shadow (alert) vs enforce (quarantine); fails open.
5. **route-on-verdict** [gate] — `_triage_single_traced` (`:357-455`): ready→plan | sentry-noise→close | already-addressed→close | else→park.
6. **maybe-decompose** [gate+llm] **[SHARED: decompose-work]** — `_maybe_decompose` (`:561-622`): complexity ≥ threshold → `run_decomposition` → `IssueDecomposer.create_epic_from_result`.
7. **record-classification** [pure] — mirror verdict + clarity/discovery hints into `IssueCache` (`:468-478`, ADR-0107).
8. **bug-reproduce** [llm+gate] — `_bug_reproducer.reproduce` (`:494-544`): `not_present`→close; must run before label swap.
9. **transition-to-plan** [pure] — deferred `transition(issue,"plan")` (`:552-555`).

Node/edge sketch:
```
entry = classify            # steps 1-3 fold into precondition gates upstream of the flow
Node("injection-screen", kind="gate")   [SHARED]
Node("classify", kind="step")           # LLM evaluate
Node("route", kind="gate")
Node("decompose", kind="step")          [SHARED]  # only when complexity gated in
Node("bug-reproduce", kind="step")
Node("record+transition", kind="step")
Edges:
  classify --(injection tripped & enforce)--> quarantine(terminal)
  classify --> route
  route --(ready)--> decompose ; route --(close verdicts)--> close(terminal) ; route --(park)--> park(terminal)
  decompose --(epic created)--> record+transition(as epic) ; decompose --(no)--> bug-reproduce
  bug-reproduce --(not_present)--> close(terminal) ; bug-reproduce --> record+transition --> ready(terminal)
```

### 2b. plan — `PlanPhase.plan_issues` (`plan_phase.py:1959`)

Per-issue pipeline: `_plan_one` (`:1420-1814`); epic lane wraps it in a gap-review convergence loop `_plan_epic_group` (`:1855`).

Ordered steps (one issue):
1. **human-steering-fetch** [pure] — `:1446` (reference-only).
2. **research-prepass** [llm+gate] — gate `_should_research` (`:453`), `research_runner.research` (`:1450`).
3. **discover-helper** [llm+gate] — gate `_should_discover_helper` (`:500`), `_run_discover_helper` (`:1486`); fires on low clarity / route-back / needs-discovery hint (ADR-0107).
4. **shape-helper** [llm+gate+HITL] — gate `_should_shape_helper` (`:590`), `_run_shape_helper` (`:1495-1627`); non-final → close-captured / close-deferred / **escalate HITL**.
5. **assumption-surfacer** [llm] **[SHARED: adversarial-review]** — `_run_assumption_surfacer` (`:1642`, `assumption_surfacer.py:59`): one-shot critic → `AdversarialState.pending_concerns`.
6. **plan** [llm] — `self._planners.plan(...)` (`:1670`): core generation.
7. **plan-review-council** [council+loop] **[SHARED: adversarial-review]** — `_run_plan_council` (`:1698`, `plan_council.py:58`): **3 voters** (builder/tester/risk_skeptic, `plan_council.py:42`) in parallel `asyncio.gather` (`:72`), wrapped in `AdversarialRetryLoop(budget=3)`; converge = `not tally.should_retry` (`:314`).
8. **already-satisfied-handling** [gate+HITL] — `:1719-1776`: validate evidence → close / escalate HITL.
9. **success/failure branch** [gate] — `:1778-1802` → `_handle_plan_success` (`:740`). *(Note: `_handle_plan_failure` (`:1272`) is defined but NOT wired into the failure branch — plan-validation failures only post a transcript today; a flow should route them to HITL.)*
   - 9a. **decompose-retry** [llm+loop] — product-track <3 sub-issues → replan once (`:744-773`).
   - 9b. **write-plan-records + plan-reviewer** [llm] — `_write_plan_records` (`:895`) runs `plan_reviewer.review` (`:928`); blocking findings recorded for READY-gate route-back.
   - 9c. **touchpoint-expand** [llm+loop-once+gate] **[SHARED: touchpoint-expand]** — `_maybe_expand_touchpoints` (`:971-1049`): first blocking review only → `touchpoint_expander.expand_touchpoints` (`:999`) → re-review once (ADR-0063).
   - 9d. **spec-ac + spec-judge** [llm+loop] **[SHARED: spec-compliance-verify / adversarial-review]** — `_run_spec_ac_and_judge` (`:346-416`): `SpecACGenerator.draft` → `SpecJudge.evaluate` in `AdversarialRetryLoop(budget=3)`; converge = `verdict=="PASS"`.
   - 9e. **transition-to-ready + spawn-subissues** [pure] — `:871-888`.
10. **epic convergence loop** [loop] — `_plan_epic_group` (`:1904`): gap-review over `range(1, max_iterations+1)`; no `replan_issues` → break; else replan flagged children.

Node/edge sketch (the council/gate steps become the shared `loop`/`gate` nodes):
```
entry = maybe-research
research? --> discover? --> shape? --(non-final)--> close|HITL
shape? --> surface-assumptions [SHARED] --> plan
plan --> plan-council [SHARED loop] --(converged)--> already-satisfied? --> write-records
                                     --(budget spent)--> forward-concerns (dark-factory) --> write-records
write-records --> touchpoint-expand [SHARED, once] --> spec-ac+judge [SHARED loop] --(PASS)--> ready(terminal)
                                                                                     --(fail budget)--> forward --> ready
any-validation-failure --> HITL(terminal)     # wire _handle_plan_failure here
```

### 2c. implement — `ImplementPhase.run_batch` (`implement_phase.py:291`) — **highest value (#10659 thrash)**

Per-issue pipeline: `_worker` (`:361`) → `_worker_inner` (`:432-540`).

Ordered steps (one issue, one attempt):
1. **claim-issue** [pure] — `_claim_issue` (`:120`); `finally` releases claim (`:407-417`).
2. **adversarial-carryover-read** [pure] — `_log_adversarial_carryover` (`:184-215`): reads plan-phase concerns (passive — no active adversarial node in implement today).
3. **existing-pr-shortcut** [gate] — `:444-468`: non-draft PR exists & not a retry → straight to review.
4. **attempt-cap-gate** [gate] — `_check_attempt_cap` (`:618-635`): `attempts = increment(); if attempts <= max_issue_attempts: proceed` (`:620-622`); else `_escalate_capped_issue` → HITL (`:605-616`). **`max_issue_attempts` default 3** (`config.py:140`).
5. **inject-reflections** [pure] — `:501-507`.
6. **run-implementation** [llm] — `_run_implementation` (`:710-843`): prior-failure/spec-gap framing (`:718-740`) → `_setup_worktree_and_branch` → `self._agents.run(...)` (`:819-824`). **This agent call is bounded by `agent_timeout` default 3600s** (`config.py:330`; applied at `base_runner.py:285`). *(The `3600` at `implement_phase.py:172` is an unrelated cache TTL.)*
7. **record-reflection** [pure] — `:511-525`.
8. **handle-result / route** [gate] — `_handle_implementation_result` (`:845-899`):
   - **zero-commit-guard** [gate] — `_is_zero_commit_failure` (`:901`) → `_handle_zero_commits` + spec review, re-queue.
   - **null-delivery-screen** [gate] — `_is_null_delivery` (`:913`) → `_handle_null_delivery` (`:942`), retry.
   - **push-branch** [pure] — `:878-881` (success or retry only).
   - **requirements-gap-flag** [llm] — `_flag_requirements_gaps` (`:1101`).
   - **spec-compliance-review** [llm] **[SHARED: spec-compliance-verify]** — `_run_spec_compliance_review` (`:972-1049`, `implement_spec_reviewer.py`): persists gaps into `spec_review_gaps` for the next attempt's prompt.
9. **resolve-PR / fresh-base-gate** [gate] — `_handle_successful_push` (`:1299`) → `_ensure_fresh_base` (`:1238`): stale base → keep in ready, retry.
10. **escalate-no-changes-to-HITL** [gate] — `_escalate_no_changes_to_hitl` (`:1334`).

**The thrash & the missing node.** There is **no no-progress / early-abort detection today** — no per-attempt diff comparison, no "same output as last attempt" check. The only screens are zero-commit and null-delivery; both simply mark `failed` and let the attempt-cap re-queue. "Diverse-retry" (`:795-798`) only reframes the prompt as "attempt N of M". So a non-converging issue can burn **up to `max_issue_attempts × agent_timeout` ≈ 3 × 3600s** before HITL. The design's **no-progress early-abort node** belongs at step 8 (`_handle_implementation_result`, `:845-899`), comparing the new branch diff against the prior attempt's before re-queuing — the analog of review's convergence-lap ledger (§2d).

Node/edge sketch (`decompose → build → spec-verify → gate` per the epic, plus the new abort node):
```
entry = attempt-cap-gate
attempt-cap --(over cap)--> HITL(terminal)
attempt-cap --(existing PR, not retry)--> review-handoff(terminal)
attempt-cap --> decompose-work [SHARED, optional] --> build (LLM, timeout-bounded)
build --> screen(zero-commit / null-delivery gate)
screen --(rejected)--> no-progress-abort [NEW gate node]
no-progress-abort --(diff == prior attempt's diff)--> HITL(terminal)          # replaces the 3600s×3 thrash
no-progress-abort --(progress made)--> re-queue-retry(terminal)
screen --(ok)--> spec-verify [SHARED] --(compliant)--> fresh-base-gate --> open-PR(terminal)
spec-verify --(gaps)--> persist-gaps --> re-queue-retry(terminal)
fresh-base-gate --(stale)--> re-queue-retry(terminal)
```
The gate — not the prompt — decides retry-vs-HITL. Reuse the §3 `convergence-gate` so implement gets lap/oscillation awareness (which review already has and implement lacks).

### 2d. review — `ReviewPhase.review_prs` (`review_phase/_phase.py:905`)

Per-PR pipeline: `_review_one` (`:963`) → `_review_one_inner` (`:1238-1327`). **This phase already contains the most-generalized convergence machinery — mostly a "lift into shared nodes" job, not a rebuild.**

Ordered steps (one PR):
1. **precondition-gate** [gate] — missing plan/review records → back to ready (`:918-926`).
2. **skip-bot/adversarial-PR-screen** [gate] **[SHARED: injection-screen]** — filter term-proposer/edge/entry-evidence + adversarial-transient PRs (`:937-958`).
3. **initial-guards** [gate] — `_run_initial_guards` (`:1328`): merge-conflict-with-main → HITL.
4. **pre-review-checks** [gate] — `_run_pre_review_checks` (`:1353`): baseline-policy-gate (`:1361`, unapproved baseline → HITL), visual-validation, code-scanning fetch, **delta-verification** `_run_delta_verification` (`:2711`, `delta_verifier.py`).
5. **pre-flight-advisor** [llm] — `_run_pre_flight_advisor` (`:1529`): focus rubric.
6. **run-review + post** [llm] — `_run_and_post_review` (`:2402`): reviewer agent `self._reviewers.review(...)` (`:2432`) → push self-fixes → REQUEST_CHANGES review.
7. **adversarial-threshold re-review** [loop] **[SHARED: adversarial-review]** — `_check_adversarial_threshold` (`:3554-3624`): APPROVE with findings < `min_review_findings` (default 3, `config.py:130`) & no thorough marker → re-review once.
8. **post-review-actions / verdict router** [gate] — `_run_post_review_actions` (`:1411`): ultra-deep fold (`:419`), self-fix re-review, **pre-merge-spec-check** [llm] **[SHARED: spec-compliance-verify]** (`:1828`, product-track), then route APPROVE/REQUEST_CHANGES to the gate.
9. **review-fix retry loop** [loop] — `_attempt_review_fix` (`:2629-2709`): **≤2 fix-then-re-review cycles** (`max_fix_attempts=2`, `:2657`).
10. **convergence gate (approve)** [gate+council] **[SHARED: convergence-gate + adversarial-review]** — `_handle_approved_review_gated` (`:3974`) → `_convergence_decision` (`:3729-3853`): deterministic check (`_approve_deterministic_check`, `:3644`: open code-scan alerts → LOOP_BACK) → **N-lens judge** `_post_verify_lens_judge` (`:3661`, lenses by blast radius via `min_review_passes_for_blast_radius`) → ADVANCE→merge | LOOP_BACK→ready | ESCALATE→HITL.
11. **convergence gate (reject)** [gate+loop] — `_handle_rejected_review_gated` (`:3872`): LOOP_BACK to ready until lap budget → ESCALATE; oscillation via `ledger.detect_outer_oscillation()` (`:3918`).
12. **HITL escalation** [gate] — `_escalate_to_hitl` (`:3423`): routes to `diagnose` stage.

Convergence caps: `max_review_fix_attempts` default 2 (`config.py:129`); `max_convergence_laps` default 3 (`config.py:516`) is the hard anti-thrash ceiling; a LOOP_BACK past the lap budget converts to ESCALATE (`:3838-3846`).

Node/edge sketch: steps 1-5 are precondition `gate`/`step` nodes; step 6 is the `review` LLM `step`; steps 7 & 10-11 are the **shared** `adversarial-review` + `convergence-gate` `loop`/`gate` nodes; step 9 is a `loop`. The review phase is the reference implementation of the shared convergence-gate — extract it first (§3), then implement/plan consume it.

---

## 3. SHARED nodes (the payoff)

The councils, gates, and retries the phases already contain **must be built once as reusable `Node`s**, not re-derived per phase (ADR-0111 Consequences). Every one below already exists as an extractable module — the P1–P3 work is wrapping it as a `Node`, not writing it.

| Shared node | Existing module (`file:symbol`) | Consumers | Signature it needs as a `Node` |
|---|---|---|---|
| **convergence-gate** | `convergence_gate.py:80` `HybridGate` / `:130` `build_review_gate` — deterministic-first + blast-radius-scaled judge → `GateResult(ADVANCE\|LOOP_BACK\|ESCALATE)` | review (**live**, `_convergence_decision` `:3729`), implement (P2 — currently only a flat attempt-cap), plan (spec-judge/council gates) | `run(state) -> state` where state carries `GateContext(issue_number, stage, blast_radius, attempts, max_attempts)`; node writes `state["gate"] = GateResult`; outgoing edges `when=lambda s: s["gate"].decision==ADVANCE/LOOP_BACK/ESCALATE`. `kind="gate"`. |
| **adversarial-review** | `adversarial_agent_runner.py:57` `SubprocessAgentRunner` (stateless one-shot critic) + stages `assumption_surfacer.py:59` `AssumptionSurfacer`, `plan_council.py:58` `PlanCouncil` (3 voters), `spec_judge.py:56` `SpecJudge`; wrapped by `adversarial_retry_loop.py` `AdversarialRetryLoop` | plan (surfacer + council + spec-judge), implement (spec-judge; today only passive carryover), review (threshold re-review + lens judge) | `run(state) -> state` with `state["draft"]` in, appends `state["concerns"]`/`state["verdict"]`; parameterized by `phase` + roster; `kind="loop"` (critic→retry→converge, budget-bounded, concerns-forward on exhaustion). |
| **spec-compliance-verify** | `implement_spec_reviewer.py:106` `SpecComplianceReviewer` Protocol / `:237` `DefaultSpecComplianceReviewer`; input `SpecReviewInput`, output `SpecReviewResult(compliant, gaps, reasoning, degraded)` | implement (`_run_spec_compliance_review` `:972`), review (`_run_pre_merge_spec_check` `:1828` + spec lens), plan (via `spec_judge`) | `run(state) -> state`: reads `issue/plan/diff/commits` → writes `state["spec"] = SpecReviewResult`; `degraded=True` fails open (compliant); feeds the convergence-gate. `kind="step"`. |
| **touchpoint-expand** | `plan_touchpoint_expander.py:146` `PlanTouchpointExpander` → `ExpandedTouchpoints` | plan (`_maybe_expand_touchpoints` `:971`), extensible to triage & `adr_touchpoint_auditor` | `run(state) -> state`: reads `plan` + blocking review → writes enriched `state["plan"]`; bounded to one expansion (ADR-0063); `kind="step"`, one-shot loop-back edge on still-blocking. |
| **injection-screen** | `triage_honeypot.py:232` `screen_issue` → `HoneypotVerdict`; `:145` `content_has_injection_directive`, `:129` `detect_tool_calls` | triage (`:325`), review bot/adversarial-PR screen (`:937`), any phase ingesting untrusted issue/PR text | `run(state) -> state`: reads untrusted text → writes `state["screen"] = HoneypotVerdict`; enforce → route to quarantine edge, shadow → alert+proceed, infra-fail → fail open. `kind="gate"`. |

**Secondary shared nodes** (build after the top-5):

- **decompose-work** — `decomposition_council.py:77` `DecompositionCouncil` / `issue_decomposer.py:42` `IssueDecomposer`. Consumers: triage (`_maybe_decompose`), implement (decompose-to-converge, ADR-0105). `kind="step"`.
- **blast-radius-classify** — `judge_independence.py:204` `classify_diff` / `:209` `requires_independent_verdict` / `review_advisor.min_review_passes_for_blast_radius`. Deterministic; **feeds** convergence-gate (scales judge passes). Consumers: plan, implement, review. `kind="step"` (pure).
- **delta-verify** — `delta_verifier.py:102` `verify_delta` (planned vs actual files, deterministic). Consumers: review (`_run_delta_verification`), implement (fresh-base/no-change checks). `kind="step"` (pure), feeds a gate.

Building these five (+3) once removes three bespoke copies each of the adversarial loop, the spec check, and the gate — the concrete win ADR-0111 predicts.

---

## 4. Prioritized migration backlog

Ranked **value (thrash-prone / high-reliability-payoff first)** × **risk (blast radius)**. Phases dominate; loops are opportunistic.

| # | Target | Value | Blast radius | Node decomposition | Reuses | Rationale |
|---|---|---|---|---|---|---|
| **1** | **wiki-compilation** (`repo_wiki_loop` + `wiki_compiler`) | Low-med | **Low** | `extract → verify shipped-claims → synthesize → validate provenance` | (new) — proves checkpoint/resume + per-node telemetry | **P1 proof.** Lowest blast radius; off the critical path; MockWorld parity is cheap. Validates the primitive before touching load-bearing phases. |
| **2** | **implement phase** | **Highest** | **High** | §2c: `attempt-cap → (decompose) → build → screen → no-progress-abort → spec-verify → gate → open-PR` | convergence-gate, spec-compliance-verify, decompose-work, blast-radius-classify | **P2, #1 per #10659.** The thrash lives here. The **new no-progress early-abort node** replaces the 3×3600s burn. Full test pyramid. |
| **3** | **plan phase** | High | Med | §2b: research/discover/shape gates → surface → plan → council → satisfied? → write-records → touchpoint-expand → spec-ac+judge → ready | adversarial-review (surfacer/council/spec-judge), touchpoint-expand, spec-compliance-verify | **P3 first** — the council & spec-judge are already modular `AdversarialRetryLoop` blocks; cleanest shared-node reuse. Also **wire `_handle_plan_failure` into the failure branch** (currently dead). |
| **4** | **review phase** | Med-high | Med | §2d: precondition gates → review → adversarial-threshold → verdict-router → fix-loop → convergence-gate(approve/reject) | convergence-gate (**source of truth**), adversarial-review, spec-compliance-verify, injection-screen | **P3 second** — already has the most-generalized gate; extract its `_convergence_decision` as the shared node *first*, then #2/#3 consume it. Mostly lift-and-share. |
| **5** | **triage phase** | Med | Med | §2a: classify → injection-screen → route → decompose → bug-reproduce → transition | injection-screen, decompose-work | **P3 last** — cleanest DAG but lowest thrash; the honeypot & decomposer are already isolated modules. |

**Opportunistic bg-worker conversions (post-P4, only if reliability data justifies):**

- `diagnostic_loop` — **best "second worker" proof after wiki**: clean `diagnose → gate → fix` 2-stage, on the HITL-recovery critical path, medium blast radius.
- `pr_unsticker_loop` — `classify-cause → resolver → reflect → merge`; medium value, self-contained.
- `adr_reviewer_loop` / `adr_review` dial — already a council; convert only to unify on the shared adversarial-review node (reconcile the §5 discrepancy first).
- `issue_refinement_loop`, `skill_prompt_eval_loop` — low priority (maintenance, off critical path, conditional multi-step).

---

## 5. What NOT to convert (and why)

1. **The 11 one-shot-transform loops + the 6 one-shot dials.** A single input→output LLM call in a DAG is pure ceremony (ADR-0111 non-goals). Keep `adr_drift_resolver`, `term_proposer`, `sampled_audit`, `sentry`, `pr_red_repair`, `sandbox_failure_fixer`, `report_issue`, `auto_agent_preflight`, `disturbance_dampener`, `entry_evidence`, `intervention_tally` as prompts. The epic's explicit keep-as-prompt set — `transcript_summary`, `term_proposer`, `triage_honeypot` — is confirmed one-shot at the runner level.
2. **The 49 already-loop/gate loops.** Their control flow is either **deterministic with no LLM to decompose** (GC, watchers, cache, budget, promotion, merge, and all the no-LLM detectors/rollups/auditors) or **already an explicit loop/gate** (`adversarial_retry_loop`, `convergence_oscillation_loop`, `gate_activator_loop`, `triage_retry_loop`, `staging_bisect_loop`). Re-expressing a `for`-loop with an oscillation check as flow nodes changes nothing — the value of flows is making *implicit* control explicit, and these are already explicit.
3. **The measurement/instrument family** (`escape_ledger`, `second_order_vitals`, `erosion_metrics`, `fitness_scorecard`, `intervention_tally`, `gate_health`, `flake_tracker`, `detector_calibration`, `live_corpus_replay`, `retrospective`). A sensor is a single `detect → report` transform; a DAG adds nothing. Pattern-B read-only ones (`intervention_tally`, `fitness_scorecard`) especially.
4. **`base_background_loop`** — the framework base class, not a worker.

### Discrepancy to resolve before P3

The epic and the P0 proposal list **`adr_review` as "keep as prompt"**, but the code (`adr_reviewer.py:327` `_run_council_session`, 3 judges × ≤3 voting rounds) shows it is **already a multi-agent council** — a `multi-step-with-verification` shape. It should either be (a) reclassified as a flow candidate that adopts the shared `adversarial-review` node, or (b) explicitly documented as an already-explicit council that stays as-is (like `adversarial_retry_loop`). Recommendation: (b) for the epic's P0–P4 blast radius, revisiting under the opportunistic backlog, since converting it buys unification not reliability. Flagging so P3 does not silently contradict the accepted proposal text.

---

## Appendix — provenance

Classifications grounded by reading each per-tick core method (`_do_work` / `_run_once` / `run_batch` / phase entry) at `origin/staging` `43b060c17`. Counts: 66 loop files (64 registered `BaseBackgroundLoop` per `docs/arch/generated/loops.md` + base + `adversarial_retry_loop` helper); 7 provider dials (`config.py:5820` `_MAINTENANCE_ROLES`). Shared-node modules verified present and extractable (§3 citations).
