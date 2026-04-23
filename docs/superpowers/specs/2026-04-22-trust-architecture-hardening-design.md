# Trust Architecture Hardening — testing the tests + attribution

- **Status:** Draft
- **Date:** 2026-04-22
- **Author:** T-rav

## How to read this

This spec establishes the shared framing for a trust-hardening initiative
with three subsystems: an adversarial skill corpus (plus a learning loop
that grows it), contract tests for the `MockWorld` fake adapters, and a
staging-red attribution bisect loop. It fixes scope, fail-mode contracts,
CI placement, and shared infrastructure — but **not** implementation
sequencing. Three separate plans follow in `docs/superpowers/plans/2026-04-22-*.md`,
one per subsystem. When they disagree with the spec, the spec wins and the
plan must be updated.

## 1. Context

HydraFlow's current trust architecture rests on three pillars:

- **Five concentric test rings** — unit, integration, scenario, E2E, regression
  — per `ADR-0044` P3 (`docs/adr/0044-hydraflow-principles.md`) and
  `ADR-0022:MockWorld` (`docs/adr/0022-integration-test-architecture-cross-phase.md`).
- **`MockWorld`-driven scenarios** with stateful fakes
  (`tests/scenarios/fakes/fake_github.py:FakeGitHub`,
  `tests/scenarios/fakes/fake_git.py:FakeGit`,
  `tests/scenarios/fakes/fake_docker.py:FakeDocker`,
  `tests/scenarios/fakes/fake_llm.py:FakeLLM`,
  `tests/scenarios/fakes/fake_hindsight.py:FakeHindsight`). Scenarios are
  release-gating per P3.10.
- **RC promotion gate** per `ADR-0042:StagingPromotionLoop`
  (`docs/adr/0042-two-tier-branch-release-promotion.md`): `staging → rc/* → main`
  only advances on a green RC promotion PR, enforced by
  `.github/workflows/rc-promotion-scenario.yml`.
- **Principles audit** per `ADR-0044:HydraFlow Principles` codifies the
  rules of the shape and makes conformance measurable.

Three gaps remain:

1. **The post-implementation skill chain is LLM-based and has no
   adversarial harness.** `src/diff_sanity.py`, `src/scope_check.py`,
   `src/test_adequacy.py`, and `src/plan_compliance.py` are prompt-driven
   heuristics that catch (or miss) bad diffs. Today nothing verifies that a
   prompt edit, a model swap, or a refactor has not silently regressed any
   of them. A silent regression here degrades every PR the system ships.
2. **`MockWorld` fakes are the foundation of the scenario ring, but
   nothing verifies they still describe real-service behavior.** When
   `gh`, `git`, `docker`, or the Claude CLI change shape, the fakes keep
   passing while production drifts. Contract/cassette drift is undetected.
3. **When a batch of PRs merges to staging and the RC promotion goes red,
   attribution is manual.** The RC PR summary names the failing scenario
   but not the culprit commit from among potentially dozens of PRs merged
   since the last green RC. An operator bisects by hand.

**Stance.** These are not "more test rings." They are tests *of* the
existing rings plus an operational feedback loop. The spec calls the
category "trust-architecture hardening" rather than "a new test tier"
precisely because each subsystem guards an existing capability — the
skill chain, the fake library, and the RC gate — rather than adding a
new one.

## 2. Scope

**In scope.** Three primary gate-side subsystems plus a six-loop
caretaker fleet that compounds trust over time:

**Primary gates (RC-boundary):**

- Adversarial skill corpus at `tests/trust/adversarial/` plus a learning
  loop (`CorpusLearningLoop`) that proposes new cases from production
  escapes.
- VCR-style contract tests for `FakeGitHub`, `FakeGit`, `FakeDocker` with
  committed YAML cassettes under `tests/trust/contracts/cassettes/`.
  Stream-replay samples for `FakeLLM` under
  `tests/trust/contracts/claude_streams/`. A `ContractRefreshLoop` that
  re-records cassettes on a weekly cadence.
- `StagingBisectLoop` that attaches to `StagingPromotionLoop`'s RC-red
  event (see prerequisite in §8), runs the RC gate's scenario command
  set in a dedicated worktree, attributes the culprit, opens an
  auto-revert PR, and files a retry issue.

**Caretaker fleet (autonomous loops):**

- `PrinciplesAuditLoop` — **foundational** — enforces `ADR-0044`
  principle conformance on HydraFlow-self and every managed target
  repo; gates onboarding of the other trust subsystems on a green
  audit. See §11.1 — everything else rests on this.
- `FlakeTrackerLoop` — detects persistently flaky tests across RC
  runs; repair before the flake rate bloats the bisect loop's flake
  filter.
- `SkillPromptEvalLoop` — runs the full adversarial corpus against
  current skill prompts on a cadence; catches slow drift between
  RC-time sampled runs.
- `FakeCoverageAuditorLoop` — flags un-cassetted adapter methods so
  the contract gate's coverage compounds rather than stagnating.
- `RCBudgetLoop` — watches RC gate wall-clock duration; escalates
  when it regresses against a rolling median.
- `WikiRotDetectorLoop` — keeps per-repo wiki cites (ADR-0032) fresh
  across every managed repo.

**Out of scope — and staying out.**

- **Mutation testing.** User declined; not a goal.
- **Rollback drill workflow.** Deferred; no `tests/trust/drills/` tree.
- **Contract tests for `FakeHindsight`.** The Hindsight API is young and
  in-house; revisit once it stabilizes.
- **Property tests on the label state machine.** Tracked separately.
- **Visual regression on the dashboard UI.** Out of scope for this
  initiative.

## 3. Constraints

### 3.1 Trust-model constraint (CI placement)

Per-PR CI stays lightweight. New trust gates land on
`.github/workflows/rc-promotion-scenario.yml`, **not**
`.github/workflows/ci.yml`. Rationale: `ADR-0042` gates releases on the
RC promotion PR, so the expensive checks belong at that boundary; PRs to
`staging` must iterate fast because `staging` is the integration branch
and agent PR volume is high.

This is a deliberate rescoping. The current `ci.yml` runs `scenario` and
`regression` on every PR — a holdover from the single-tier branch model
that `ADR-0042` replaced. Realigning those jobs is tracked separately and
is **not** a prerequisite for this spec; the new trust gates respect the
ADR-0042 placement policy from day one regardless of whether the
existing misplacements get cleaned up first.

Per `ADR-0044` P5 (CI and branch protection), CI and local gates must not
diverge. `make trust` runs locally and in `rc-promotion-scenario.yml` with
the same exit codes.

### 3.2 Autonomy stance (load-bearing)

Every loop in this initiative terminates in one of two outcomes: **a fix
lands automatically**, or **the system escalates to a human**. There is
no "waits for human review" default on the happy path.

- **Happy path = no humans.** Self-validation, agent review, quality
  gates, and auto-merge run in sequence. A human sees results through
  the normal factory channels (dashboard, merged PR list) — not through
  an inbox of pending approvals.
- **Failure path = escalation, not pause.** When a loop cannot close its
  own workflow within a bounded retry budget (default 3 attempts per
  cycle), it files a `hitl-escalation` issue labeled with the failure
  class. The loop records the escalation and moves on — it does not
  spin waiting.
- **"Fire" criteria for HITL.** Only true safety trips pull a human in:
  - A guardrail breached (e.g., a second auto-revert in one RC cycle —
    see §4.3).
  - Self-validation fails unrecoverably (e.g., a synthesized corpus
    case won't even parse).
  - A primary repair attempt created a *new* red the loop cannot
    resolve.
- **Review is not bypassed — humans are.** Refresh-loop PRs,
  corpus-learning PRs, and auto-revert PRs all flow through the
  standard agent-reviewer + quality-gate path. `src/reviewer.py`
  enforces rigor; `make quality` enforces correctness; auto-merge
  happens only on green. This stance skips *human approval*, not
  *review itself*.

This stance overrides individual subsystem descriptions. If §4.1–§4.11
appear to describe a human gate anywhere on the happy path, that is a
drafting bug — treat §3.2 as authoritative and auto-merge with
guardrails.

**Escalation lifecycle.** Every `hitl-escalation` issue follows one
lifecycle: the loop files it, a human closes it (with or without a
fix), and the associated dedup key in `src/dedup_store.py:DedupStore`
clears on issue close (subscribe to the GitHub `issues.closed` event
via the existing issue-watcher path, or poll closed issues on a
cadence). Without this, a loop that escalates once stays paralyzed:
the dedup key blocks re-fire, but the escalation has already been
resolved. Every loop's plan must wire this lifecycle.

**Kill-switch contract.** Every loop this spec introduces must honor
a `<loop_name>_enabled` config field (default `True`) that, when set
`False`, causes the loop's tick to exit immediately. Operators flip
the switch via the System tab when a loop misbehaves. This is
load-bearing for operability: a loop bug that opens 100 revert PRs
per hour must have a faster stop than "ship a fix through the
pipeline." Matches `ADR-0044` P5 (operator control) and the existing
`*_enabled` config pattern (see `src/config.py` for conventions).

## 4. Subsystems

### 4.1 Adversarial skill corpus (+ learning loop)

**Purpose.** Detect silent regressions in the four post-implementation
skills (`src/diff_sanity.py`, `src/scope_check.py`,
`src/test_adequacy.py`, `src/plan_compliance.py`) whenever prompts, model
settings, or the skill-dispatch path changes. Each case in the corpus is
a diff that a named skill **must** flag; the harness is red if the skill
lets it through.

#### v1 — hand-crafted corpus

Layout:

```
tests/trust/adversarial/
├── __init__.py
├── test_adversarial_corpus.py     # harness (iterates cases/)
└── cases/
    └── <case_name>/
        ├── before/                # pre-diff snapshot subset
        ├── after/                 # post-diff snapshot subset
        ├── expected_catcher.txt   # one of: diff-sanity | scope-check | test-adequacy | plan-compliance
        └── README.md              # human-readable description + keyword
```

- Each `case_name` directory is the *minimum* subset of a repo needed to
  reproduce the bug class — typically 1–4 files in each of `before/` and
  `after/`. Harness synthesizes the diff as `git diff before/ after/`
  equivalent.
- `expected_catcher.txt` contains exactly one registered post-impl skill
  name (read from the live skill registry at harness start —
  `src/skill_registry.py` or equivalent), newline-terminated, plus the
  sentinel `none` for pass-through cases (see §7 "End-to-end per
  subsystem"). Adding a new post-impl skill does not require a spec
  edit; the harness validates against whatever the registry returns.
- `README.md` describes the bug class in one paragraph and names at least
  one **keyword** the skill's RETRY reason must contain (so the assertion
  is stronger than "skill said RETRY"; it also says "skill saw the right
  thing").

**Harness.** `tests/trust/adversarial/test_adversarial_corpus.py`
parameterizes over every directory under `cases/`. For each case:

1. Build the diff from `before/` and `after/`.
2. Invoke the real skill prompt via the production dispatch path
   (`src/base_runner.py`'s skill invocation — or the smallest thin shim
   that calls the same prompt-build + parse functions used in
   production; the plan picks the shim surface).
3. Assert the skill named in `expected_catcher.txt` returns RETRY.
4. Assert the RETRY reason contains the keyword listed in `README.md`
   (case-insensitive substring match).

**v1 seed corpus — minimum coverage.** The implementer seeds ~20–25
cases spanning, at minimum:

- Missing test for a new public function or class (→ `test-adequacy`).
- Renamed symbol without callsite update (→ `diff-sanity`).
- NOT-NULL / required-field violation in a Pydantic model update
  (→ `diff-sanity`).
- `AsyncMock` used where a stateful fake in `tests/scenarios/fakes/`
  already exists (→ `test-adequacy`).
- Scope-creep diff: an unrelated module edited alongside the target
  change (→ `scope-check`).
- Plan-divergence diff: implementation contradicts a step in the
  referenced plan (→ `plan-compliance`).

v1 ships first as an RC gate (`make trust-adversarial` → wired into
`rc-promotion-scenario.yml`).

#### v2 — `CorpusLearningLoop`

`src/corpus_learning_loop.py`, a new `BaseBackgroundLoop`, watches for
**escape signals** — bugs that merged to `main` despite the skill gate —
and proposes a new case for each.

**Escape-signal source (default).** `hydraflow-find` issues tagged with
the `skill-escape` label. The label is not hard-coded: a config knob
`corpus_learning_signal_label` (default `skill-escape`) lets operators
flip to a different label without a code change. Alternative source
mechanisms are listed in §9.

**Per-escape workflow.**

1. Read the escape issue body and the reverted commit (or the fix PR)
   from the linked references.
2. Synthesize a minimal `before/after` pair reproducing the class of
   bug, pick the `expected_catcher`, and draft the `README.md`. **The
   plan picks the synthesis mechanism** — two viable options: (a) the
   loop dispatches an LLM call in-process through `src/base_runner.py`
   (lower latency, self-contained), or (b) the loop files a routing
   issue with label `corpus-synthesis-task` and lets the standard
   implement phase handle it (higher latency, reuses existing
   infrastructure). Either is consistent with §3.2.
3. **Self-validation gate.** Before opening a PR, the loop verifies:
   1. The synthesized `before/` + `after/` parses (Python syntax, no
      import errors).
   2. Lint passes on the synthesized files (`make lint-check` scoped
      to the new case directory).
   3. The named `expected_catcher` skill **actually returns RETRY** on
      the synthesized diff with the claimed keyword. A case the loop
      cannot prove flags the right thing is rejected as a
      self-validation failure — the loop does not propose cases it
      cannot stand behind.
4. **Open PR and auto-merge per §3.2.** Cases that pass
   self-validation flow through the standard agent-reviewer +
   quality-gate + auto-merge path. No human approval on the happy
   path.
5. **Escalation.** Self-validation failure 3× on the same escape
   issue → label it `hitl-escalation`, `corpus-learning-stuck`,
   record the three rejected attempts in the issue body, move on.

Rationale for auto-merge: a new corpus case is a new test, not a
production-code change. The self-validation gate proves the case
actually catches what it claims to catch; `make quality` enforces the
usual quality bar. The risk profile is low; holding these PRs for
human review contradicts §3.2.

**Correlated-failure mitigation.** The loop uses an LLM to synthesize
cases for skill failures the LLM family may share. Without a cross-check
the corpus can accumulate cases that share the originating model's
blind spots — false trust. Mitigate with two mechanisms:

1. **Cross-model synthesis (not cross-model validation).** The
   **synthesis** step uses a *different* model from the one the
   production skill runs on, so the case isn't biased by the
   production model's blind spots. Validation ALWAYS runs the skill
   with its production configuration (whatever `BUILTIN_SKILLS`
   actually dispatches) — otherwise we'd be verifying the case
   against a model the skill doesn't use in practice, which makes the
   corpus misleading. Config fields:
   `corpus_learning_synthesis_model` (default `opus`, or any model
   distinct from the production skill's model — read the skill
   registry to check). If the synthesis model matches the skill's
   production model, the loop logs a warning and proceeds with
   reduced diversity. If `opus` is unavailable, fall back to `sonnet`
   and emit a provenance note.
2. **Provenance tagging + periodic sample audit.** Every auto-generated
   case has `provenance: learning-loop` recorded in its
   `README.md` front-matter. `SkillPromptEvalLoop` (§4.6) samples 10%
   of learning-loop cases each week and flags cases whose
   `expected_catcher` skill passes them unexpectedly (indicating the
   case may be too weak) — files a `hydraflow-find` with label
   `corpus-case-weak` for human review.

**Five-checkpoint wiring** per `docs/agents/background-loops.md`:

1. `src/service_registry.py` — dataclass field + `build_services()`
   instantiation.
2. `src/orchestrator.py` — entry in `bg_loop_registry` dict.
3. `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`.
4. `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`.
5. `src/config.py` — interval `Field` + `_ENV_INT_OVERRIDES` entry.

LLM model override (per `docs/agents/background-loops.md`): add
`corpus_learning_model` to `src/config.py` with env var
`HYDRAFLOW_CORPUS_LEARNING_MODEL`, default `sonnet` (case synthesis is a
structured summarization task; `opus` is not justified).

**Rollout.** v1 ships first as an RC gate. v2 ships later as a
caretaker loop per `ADR-0029`. The plans split the two subsystems so v2
can slip without blocking v1.

### 4.2 Contract tests for fakes

**Purpose.** Detect drift between `tests/scenarios/fakes/*` and the real
adapters they stand in for. A passing scenario suite means nothing if the
fake speaks a dialect the real service no longer accepts.

#### Cassette layout

```
tests/trust/contracts/
├── __init__.py
├── test_fake_github_contract.py
├── test_fake_git_contract.py
├── test_fake_docker_contract.py
├── test_fake_llm_contract.py
├── cassettes/
│   ├── github/
│   │   └── <interaction>.yaml
│   ├── git/
│   │   └── <interaction>.yaml
│   └── docker/
│       └── <interaction>.yaml
└── claude_streams/
    └── <sample>.jsonl
```

**Cassette schema (shared across `github/`, `git/`, `docker/`).** YAML,
one file per interaction:

```yaml
adapter: github | git | docker
interaction: <short-slug>
recorded_at: 2026-04-22T14:07:03Z
recorder_sha: <git sha of HydraFlow when recording>
fixture_repo: <test-scoped repo or container image pinned for this cassette>
input:
  command: gh pr create ...            # or: git commit -m ..., docker run ...
  args: [...]                          # argv after the command
  stdin: null | "<string>"             # optional
  env: {}                              # only non-default env overrides
output:
  exit_code: 0
  stdout: |
    ...
  stderr: |
    ...
normalizers:                           # fields the replay side skips byte-exact
  - pr_number
  - timestamps.ISO8601
  - sha:short
```

**`normalizers` list** names fields that must match **shape** but not
exact bytes — PR numbers, ISO timestamps, short SHAs. The harness runs
the normalizers on both sides before comparing. Without normalizers the
cassette would rot the moment anything auto-increments.

#### Two-sided assertion harness

Each `test_fake_<adapter>_contract.py` runs two sides per cassette:

**Replay side (every RC gate run).** Feed the cassette's `input` into
the corresponding fake from `tests/scenarios/fakes/`. Assert the fake's
output matches the cassette's `output` field-by-field, after
normalizers. This catches *fake regressions*: the fake no longer
matches the recorded real-service behavior.

**Freshness side (`ContractRefreshLoop`, weekly).** The refresh loop
is the freshness monitor — see the `ContractRefreshLoop` section below
for the full flow. Summary: it invokes the **real adapter** — `gh`,
`git`, or `docker run <pinned-image>` — against the cassette's
`fixture_repo` (or scratch container) and diffs the real output against
the committed cassette. Diffs do not fail the RC gate; they trigger the
autonomous refresh workflow below. Per §3.2, refresh PRs auto-merge
when the replay side still passes with the new cassette; when it
doesn't, a companion `fake-drift` issue routes repair through the
factory. No human approval on the happy path.

Rationale for non-blocking freshness: `gh` CLI releases, `git`
behavior, and `docker` output are not change-controlled by us. A
third-party version bump is a signal that triggers the autonomous
refresh, not a page that blocks the RC.

#### `FakeLLM` is different

The real `claude` CLI is non-deterministic; there is no cassette we can
diff exactly. Instead:

- Record stream samples: `claude ... --output-format stream-json` run
  against a short, stable prompt, saved as `<sample>.jsonl` under
  `tests/trust/contracts/claude_streams/`.
- Replay side asserts that `src/stream_parser.py`'s parser consumes
  every sample without error and emits the expected tool-use /
  text-block boundaries.
- Freshness side is coverage-shaped, not output-shaped: the refresh
  loop re-records a fresh sample; if the parser errors on the new
  sample, that's a hard signal the Claude streaming protocol changed,
  and it files a `hydraflow-find` with label `stream-protocol-drift`.

#### Adapters covered in v1

| Fake | Real adapter | Fixture target |
|---|---|---|
| `FakeGitHub` | `gh` CLI | A disposable test repo (throwaway; not the HydraFlow repo). |
| `FakeGit` | `git` CLI | A fixture repo under `tests/trust/contracts/fixtures/git_sandbox/`. |
| `FakeDocker` | `docker run` | A pinned trivial image (e.g. `alpine:3.19`). |
| `FakeLLM` | `claude` CLI streaming mode | Short prompts; samples committed as `.jsonl`. |

#### `ContractRefreshLoop` — full caretaker (refresh + auto-repair)

`src/contract_refresh_loop.py`, a new `BaseBackgroundLoop`, weekly
cadence. Per §3.2, the loop is autonomous end-to-end: it detects drift,
repairs both sides of the contract (cassettes and fakes), and merges
the fix. Humans enter only on escalation.

**On fire (weekly).**

1. Re-record every cassette and stream sample against live services.
2. Diff new recordings against committed cassettes. **No diff →
   no-op**, return.
3. **Diff detected.** Commit refreshed cassettes to a branch
   `contract-refresh/YYYY-MM-DD` and open a PR against `staging`.
4. Run contract replay tests against the new cassettes:
   - **Replay passes** → fakes still speak the dialect. This is a
     "cassette-only drift" refresh. PR flows through standard
     agent-reviewer + quality-gate + auto-merge per §3.2.
   - **Replay fails** → a fake diverged. The loop files a companion
     `hydraflow-find` issue with label `fake-drift` naming which
     adapter, which method, which field moved. The factory picks up
     the issue and routes it through the standard implement phase
     (`src/implement_phase.py`); the implementer agent edits
     `tests/scenarios/fakes/fake_*.py` to match the new cassette,
     re-runs contract tests, and lands a fix PR on `staging` that
     auto-merges on green.
5. **Stream-protocol drift.** If `src/stream_parser.py` errors on a
   newly-recorded `claude` stream sample, file a `hydraflow-find`
   with label `stream-protocol-drift`; the factory routes the repair
   through the standard implement phase against
   `src/stream_parser.py` itself.
6. **Escalation.** If the implementer loop fails to close a
   `fake-drift` or `stream-protocol-drift` issue after 3 attempts
   (governed by the existing factory retry budget — the plan picks
   the correct config field, likely `max_issue_attempts` or a
   dedicated `max_fake_repair_attempts`), the issue gets labeled
   `hitl-escalation`, `fake-repair-stuck` (or `stream-parser-stuck`)
   and the `ContractRefreshLoop` stops opening new refresh PRs for
   that adapter until the escalation closes.

**Rationale for auto-repair both sides.** A passing cassette with a
divergent fake is still a red gate — the scenario ring would silently
trust a wrong fake. The loop's responsibility is the full contract
(real output ↔ cassette ↔ fake output); it must close drift on
whichever side broke. Test-infrastructure code (fakes) is lower risk
than production code and fits the §3.2 happy path.

**PR ordering for cassette + fake drift.** When both sides drifted,
the refresh PR (new cassettes) and the companion fake-repair PR (fake
edits) must not merge independently or the tree goes red between
them. Mechanism: the refresh PR stays as draft until the companion
`fake-drift` issue closes (its fix PR merges); once the fake fix is
on `staging`, the refresh PR converts to ready and auto-merges in the
next cycle. Alternatively — and simpler — the companion repair lands
*on the refresh PR's branch* (the implementer is dispatched against
that branch, not `staging`), so both changes merge atomically. Plan
picks; recommend the atomic-branch option.

**Rate-limit and cost discipline.** Weekly recording against live
`gh` CLI, `git`, `docker`, and `claude` per-adapter consumes real
API/CLI budget. For HydraFlow-self this is cheap; at multi-repo scale
(§11) this compounds. Constraints the plan must encode:

- Throttle: at most one `ContractRefreshLoop` run per adapter per
  24h, regardless of how many managed repos are registered (cassettes
  are shared across repos — see §11.2, one cassette set covers all).
- Scatter: when recording M adapters, sleep `throttle_between_adapters_s`
  (default 30s) between recordings to avoid rate-limit bursts on any
  single provider.
- Telemetry: each recording call emits to `src/prompt_telemetry.py`
  (for `claude`) and `src/trace_collector.py` (for subprocesses) so
  the per-loop cost dashboard in §4.11 shows `ContractRefreshLoop` as
  a line item.
- Alert: if a weekly recording fails due to rate limit or auth, file
  `hydraflow-find` with label `contract-refresh-throttled`; the loop
  backs off and retries next cycle. No escalation until 3 consecutive
  failures.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `contract_refresh_interval`, default `604800` seconds (7 days).
No per-worker LLM model override — the loop itself does not call the
LLM; the dispatched implementer uses the standard implementer model.

**Why commit cassettes to the repo.** Cassettes are small (< 10 KB
each); no secrets (everything records against disposable test repos and
pinned images); review-visible via `git diff` on the refresh PR.
Committing them matches the rest of HydraFlow's "state in config,
history in git" stance (`ADR-0044` P1 Documentation Contract — the
wiki/ADR spine as the source of truth for knowledge, and git as the
audit log).

### 4.3 Staging-red attribution + auto-revert

**Purpose.** Close the full loop from "RC is red" to "green RC with the
culprit reverted and a retry issue filed" — without pulling a human in
on the happy path. Per §3.2, the loop reverts the bad commit, routes
the original work back through the factory as a retry, and only pulls a
human in when a safety guardrail trips.

**`StagingBisectLoop`** — `src/staging_bisect_loop.py`, a new
`BaseBackgroundLoop`.

**Trigger.** The loop subscribes to a new `rc_red` event emitted by
`src/staging_promotion_loop.py:StagingPromotionLoop._handle_open_promotion`
when CI fails on an RC PR. See §8 for the prerequisite — today the
method files a `hydraflow-find` issue but does not emit an event; the
plan adds the emission.

**On fire.**

1. **Flake filter.** Before bisecting, re-run the RC gate's
   scenario suite against the RC PR's head up to **two additional
   times** (default; config `staging_bisect_flake_reruns`, default
   2). Apply 2-out-of-3 logic: if either retry passes and the
   original failed, treat as flake (log `warning`, increment
   `flake_reruns_total`, exit — no bisect, no revert). If both
   retries also fail, the red is confirmed and bisect proceeds.
   Single-retry flake filters miscall ~50% of flakes as real
   regressions and over-trigger auto-revert; 2-of-3 is the minimum
   defensible bar.
2. **Bisect.** Read `last_green_rc_sha` from
   `src/state/__init__.py:StateTracker` (written by
   `StagingPromotionLoop` on each successful promotion — see §8).
   Read `current_red_rc_sha` from the RC PR's head. In a dedicated
   worktree under `<data_root>/<repo_slug>/bisect/<rc_ref>/`
   (`ADR-0021` P9 persistence):
   - `git bisect start <current_red_rc_sha> <last_green_rc_sha>`
   - `git bisect run` against the RC gate's full scenario command
     set — at minimum `make scenario && make scenario-loops` per the
     current `rc-promotion-scenario.yml` steps. The plan adds a
     dedicated Makefile target (e.g. `make bisect-probe`) that mirrors
     the RC gate's scenario commands so changes to the RC gate
     automatically update what bisect runs. Critical: the bisect
     probe must match the RC gate exactly; a scenario-loops-only
     regression won't bisect if the probe runs `make scenario` alone.
3. **Attribution.** Parse bisect output. First-bad commit = the
   culprit. Resolve the containing PR via
   `gh api repos/.../commits/<sha>/pulls`; call the PR number `N`.
4. **Safety guardrail (per-cycle).** `StateTracker` tracks
   `rc_cycle_id` and `auto_reverts_in_cycle` (count). If
   `auto_reverts_in_cycle > 0`, **do not revert again in this cycle.**
   A second red after a first revert means either the bisect was
   wrong or the damage is broader than one PR — escalate: file
   `hitl-escalation`, `rc-red-bisect-exhausted` with both bisect logs
   and stop. Reset the counter only when a green RC promotes.

5. **Safety guardrail (per-work-item lifetime cap).** Every retry
   issue carries a `retry_lineage_id` — **always the SHA of the
   FIRST culprit in the chain**, never rotated per cycle. A new
   lineage_id is generated only when bisect attributes a culprit
   whose containing PR is NOT in any existing lineage
   (`StateTracker.retry_lineage_attempts` is keyed by lineage_id and
   maps to a count plus the set of PR numbers in that lineage). When
   filing a new retry issue:
   - Look up the culprit PR number in
     `retry_lineage_attempts`; if it belongs to an existing lineage,
     increment that lineage's counter.
   - Otherwise, start a new lineage rooted at this culprit's SHA.
   If the counter would exceed `max_retry_lineage_attempts` (default
   **2**), do NOT revert and do NOT retry again — escalate:
   `hitl-escalation`, `retry-lineage-exhausted`, naming the lineage
   and linking all prior retry/revert PRs. Bounds the worst case
   where a bug is intrinsic to the work, not the commit: original →
   revert → retry → red → revert → retry → red → human. Without this,
   the loop can churn on an un-automatable task indefinitely.

6. **Reverting a revert.** A bisect that identifies an earlier
   `auto-revert/*` commit as the culprit is anomalous (the revert
   itself triggered the red) — escalate:
   `hitl-escalation`, `bisect-culprit-is-auto-revert`. Do not
   un-revert; a human must disentangle.
7. **Revert PR.** Create branch
   `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}` off `staging`. Run
   `git revert <culprit_sha>` for a single commit, or
   `git revert -m 1 <merge_sha>` for a merge commit. Push. Open PR
   against `staging` via `src/pr_manager.py:PRManager`:
   - Title: `Auto-revert: PR #{N} — RC-red attribution on <test_name>`
   - Body: culprit SHA, failing scenario test names, RC PR URL,
     `git show <sha> --stat`, bisect log, link to the retry issue
     (step 6).
   - Labels: `hydraflow-find`, `auto-revert`, `rc-red-attribution`.
8. **Retry issue (with full context carry-over).** Simultaneously
   file a new `hydraflow-find` issue via
   `src/pr_manager.py:PRManager.create_issue`:
   - Title: `Retry: <original PR title>`
   - Body MUST include:
     - Link to the reverted PR and its merged commit SHA.
     - Link to the **original issue** the reverted PR addressed
       (resolved via `gh api repos/.../pulls/{N}` → `body` /
       closing-keywords parser; if unresolvable, leave the field
       with `unresolved`).
     - Link to the **plan doc** if one exists for the original issue
       (`docs/superpowers/plans/` — find by grepping for the issue
       number).
     - Full bisect log, failing test names, time bounds.
     - `retry_lineage_id` (the original culprit SHA or a UUID,
       recorded in `StateTracker`).
   - Labels: carry over any labels from the original issue except
     `hydraflow-*` state labels — preserves epic, priority, area
     tags. Always add `hydraflow-find`, `rc-red-retry`. The standard
     pipeline picks up `hydraflow-find` issues; the factory re-does
     the work with original-context intact.
9. **Auto-merge path (per §3.2).** The revert PR flows through the
   standard agent-reviewer + quality-gate + auto-merge path. The
   retry issue flows through the standard implement/review pipeline.
   No human approval on either happy path.
10. **Outcome verification.** After the revert merges, the next
   `StagingPromotionLoop` cycle creates a fresh RC. The loop waits
   (bounded watchdog: default 2 RC cycles or 8 hours, whichever is
   shorter) for the RC to go green.
   - **Green:** log at `info`, increment
     `StateTracker.auto_reverts_successful`, reset
     `auto_reverts_in_cycle`, close the loop cleanly.
   - **Still red:** escalate `hitl-escalation`,
     `rc-red-post-revert-red` with both the original bisect log and
     the new RC's failure output. The revert stays in place (it
     eliminated one red; pulling it out blindly could introduce
     another).
   - **Watchdog timeout:** escalate
     `hitl-escalation`, `rc-red-verify-timeout` — RC pipeline may be
     stalled for unrelated reasons; the human can disambiguate.
11. **Cleanup.** `git worktree remove --force` on the bisect worktree
   regardless of outcome.

**Revert edge cases.**

- **Merge conflicts on revert.** `git revert` exit non-zero with
  conflicts → abandon immediately, do not attempt auto-resolution.
  Escalate `hitl-escalation`, `revert-conflict` with the conflicting
  paths. Conflicts mean subsequent PRs depend on the culprit; fixing
  requires judgment the loop does not have.
- **Merge commits (squash vs merge commits).** `staging` uses merge
  commits per `ADR-0042` merge-strategy decision. Use
  `git revert -m 1 <merge_sha>` by default. Single-commit PRs
  (uncommon on `staging`) use `git revert <sha>`.
- **Dependent PRs already landed on top.** The revert may break
  follow-up work. Acceptable trade-off: the follow-up can retry via
  its own issue. The revert is the cheapest safe undo; broader
  dependency surgery is a human decision.

**Idempotency.** `src/dedup_store.py:DedupStore` keyed by
`(rc_pr_number, current_red_rc_sha)` — a re-fire for the same RC does
not double-bisect or double-revert. If the repo has advanced past the
bisect range (e.g. `last_green_rc_sha` no longer reachable due to a
rebase), skip with a warning log — idempotent no-op, do not fail the
loop.

**Error handling.** Bisect harness failures (bisect itself errors,
`make scenario` errors for a reason unrelated to the regression) log at
`warning` per `ADR-0044` P7 Sentry rules and file a
`hitl-escalation` with label `bisect-harness-failure`. These are
infrastructure bugs, not scenario regressions, and the loop cannot
self-heal them.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `staging_bisect_interval`. The loop is event-driven, not
polling, so the interval acts as a watchdog poll for missed events;
default `600` seconds. No per-worker LLM model override (no LLM call).

**Probe/RC-gate sync test.** `make bisect-probe` must mirror the RC
gate's scenario steps. A scenario-loop-only regression won't bisect
if probe runs `make scenario` alone. Add a test at
`tests/test_bisect_probe_sync.py` that parses both `Makefile`
(bisect-probe target) and `.github/workflows/rc-promotion-scenario.yml`
(scenario steps), extracts the called targets/commands, and asserts
equality — flags drift before bisect silently runs a subset.

### 4.4 Principles audit + drift detector (foundational)

**Purpose.** Enforce `ADR-0044` principle conformance on HydraFlow-self
and every managed target repo. Without this, the other trust
subsystems guard a repository shape that may not be in place — see
§11.1. This is the caretaker the spec says is currently missing.

**`PrinciplesAuditLoop`** — `src/principles_audit_loop.py`, new
`BaseBackgroundLoop`. Weekly cadence + triggered on managed-repo
onboarding.

**On fire — per repo.**

1. For HydraFlow-self, run `make audit --json` against the current
   working tree; for each managed target repo in the factory registry,
   refresh a shallow checkout under
   `<data_root>/<repo_slug>/audit-checkout/` and run `make audit
   --json` there. Save each result to
   `<data_root>/<repo_slug>/audit/<YYYY-MM-DD>.json`.
2. Read last-green audit snapshot from
   `src/state/__init__.py:StateTracker`. Diff pass/fail sets at the
   `check_id` level (P1.1, P2.4, etc.).
3. For each check that regressed from PASS to FAIL, file a
   `hydraflow-find` issue via `src/pr_manager.py:PRManager.create_issue`:
   - Title: `Principles drift: {check_id} regressed in {repo_slug}`
   - Body: the ADR-0044 row (rule, source, what, remediation), the
     audit output snippet, the last-green snapshot date/SHA.
   - Labels: `hydraflow-find`, `principles-drift`,
     `check-{check_id}`.
4. Factory picks up the issue; standard implement phase routes the
   repair (for STRUCTURAL checks, scaffold the missing file; for
   BEHAVIORAL, fix the failing tool or target; for CULTURAL, the plan
   may require a human assist — CULTURAL regressions escalate after
   1 failed attempt since they are not machine-repairable).
5. On successful remediation + audit green, update the last-green
   snapshot for that repo.

**Onboarding gate.** A new managed target repo is signaled by an
entry in `src/config.py:managed_repos` (the spec picks this
mechanism; not a label, not a separate API — one place in config,
one source of truth). On each loop tick, `PrinciplesAuditLoop`
compares `managed_repos` to the set it has already audited; new
entries trigger an onboarding audit:

- The loop runs `make audit --json` against a shallow checkout of the
  new repo.
- **P1–P5 FAILs block the factory pipeline, not just trust
  subsystems.** The gate writes `managed_repos_onboarding_status[slug] = "blocked"`
  to `StateTracker`. The orchestrator (`src/orchestrator.py`) reads
  this field and skips the repo in its pipeline dispatch loop until
  status flips to `ready`. This is the stronger enforcement: without
  it, the factory could still run pipelines on a non-conformant repo
  while the trust subsystems abstain — cargo-cult selectivity. P1–P5
  (documentation contract, layers, testing rings, quality gates,
  CI + branch protection) are the load-bearing set.
- File `hydraflow-find` labeled `onboarding-blocked` with the
  specific failing checks. Factory dispatches the implementer to
  remediate (or routes to `make init` for greenfield scaffolding).
  When remediation merges and a re-audit passes P1–P5,
  `managed_repos_onboarding_status[slug]` flips to `ready` and the
  factory begins processing.
- **P6–P10 FAILs warn but do not block.** P6 (loops/labels) is
  optional for non-orchestration repos; P7–P10 are high-value but
  not structurally required for the trust gates to function.

**HydraFlow-self CI gate.** A regression on HydraFlow's own principles
between weekly audits must not be able to land. Add an `audit` job to
`.github/workflows/ci.yml` (every PR to staging, not just the RC
promotion — this is the one gate that runs everywhere because
principles must hold on every commit):

```yaml
audit:
  name: Principles Audit
  needs: changes
  if: needs.changes.outputs.python == 'true' || needs.changes.outputs.ci == 'true'
  runs-on: ubuntu-latest
  timeout-minutes: 5
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.11" }
    - run: uv sync --all-extras
    - run: make audit
```

Failing `make audit` fails the PR. The `.hydraflow-audit-baseline`
file anchors P10.3 to exclude historical drift; other checks are
absolute. This gate is the machinery that enforces §11.1's "principles
as foundation" for HydraFlow-self.

**Escalation.** STRUCTURAL/BEHAVIORAL regressions: after 3 repair
attempts, label `hitl-escalation`, `principles-stuck`. CULTURAL
regressions: after 1 failed attempt, label immediately — a human must
confirm branch protection, review settings, etc.

**Five-checkpoint wiring** (same five slots as §4.1). Config interval
field: `principles_audit_interval`, default `604800` (7 days). No LLM
model override — the loop itself reads the audit tool's JSON; the
dispatched implementer uses the standard model.

### 4.5 Flake tracker

**Purpose.** Detect persistently flaky tests before the `StagingBisectLoop`
flake filter bloats and masks real regressions.

**`FlakeTrackerLoop`** — `src/flake_tracker_loop.py`,
`BaseBackgroundLoop`. Runs after each RC CI completion (watchdog
cadence default `14400` = 4h, matching `rc_cadence_hours`).

**On fire.**

1. Query the last 20 RC workflow runs via `gh api`. For each run,
   extract per-test pass/fail via the JUnit XML artifacts the CI
   uploads (the plan adds artifact emission if not already present).
2. For each test with a mixed pass/fail record inside the window,
   increment `flake_count[test_name]` in `StateTracker`.
3. When `flake_count[test_name] > flake_threshold` (default: 3 fails
   in 20 runs), file a `hydraflow-find`:
   - Title: `Flaky test: {test_name} (flake rate: {N}/20)`.
   - Body: run URLs, stack traces per occurrence, time span.
   - Labels: `hydraflow-find`, `flaky-test`.
4. Factory dispatches implementer; standard repair path (fix the race,
   add deterministic wait, or quarantine-then-remove the test).

**Escalation.** After 3 repair attempts, `hitl-escalation`,
`flaky-test-stuck`.

**Five-checkpoint wiring**. Config `flake_tracker_interval` default
`14400`, `flake_threshold` default `3`.

### 4.6 Skill-prompt eval

**Purpose.** Catch slow drift in post-impl skill behavior that the
RC-time sampled adversarial corpus misses. The RC gate runs a sampled
subset; this loop runs the full corpus against current prompts on a
cadence.

**Depends on §4.1.** The adversarial corpus must exist.

**`SkillPromptEvalLoop`** — `src/skill_prompt_eval_loop.py`,
`BaseBackgroundLoop`, weekly.

**On fire.**

1. Run `make trust-adversarial` over the **full** committed corpus
   (not the RC-time sampled subset). Record pass/fail per case.
2. Diff against the last-green eval snapshot in `StateTracker`.
3. For each case that regressed from PASS to FAIL, file a
   `hydraflow-find`:
   - Title: `Skill prompt drift: {skill} missed {case_name}`.
   - Body: case diff, expected RETRY reason, actual output, link to
     the skill's prompt-file commit history.
   - Labels: `hydraflow-find`, `skill-prompt-drift`.
4. Factory dispatches implementer; standard repair path edits the
   skill prompt or the skill's code.

**Escalation.** After 3 repair attempts, `hitl-escalation`,
`skill-prompt-stuck`.

**Five-checkpoint wiring**. Config `skill_prompt_eval_interval`,
default `604800`.

### 4.7 Fake coverage auditor

**Purpose.** Flag un-cassetted adapter methods so contract coverage
compounds rather than stagnating at whatever was cassetted on day one.

**Depends on §4.2.** Cassette infrastructure must exist.

**`FakeCoverageAuditorLoop`** — `src/fake_coverage_auditor_loop.py`,
`BaseBackgroundLoop`, weekly.

**On fire.**

1. Introspect each fake class under `tests/scenarios/fakes/` via the
   AST (`ast.parse`). Read **two method sets**: (a) public methods
   not prefixed `_` — the methods that mirror the real adapter's
   surface; (b) test-facing helpers — `script_*`, `fail_service`,
   `heal_service`, `set_state`, and any other non-private method that
   scenarios reach into. Both sets are part of the contract (the
   first with the real adapter, the second with scenario tests); gaps
   in either deserve a report.
2. Parse all cassettes under `tests/trust/contracts/cassettes/<adapter>/`
   and collect the real-adapter method invoked by each (`input.command`
   is the source of truth). Separately, grep `tests/scenarios/` for
   calls to the test-facing helpers to assert they're exercised.
3. Compute coverage: a fake method is covered if at least one cassette
   exercises its real-adapter counterpart.
4. For each uncovered method, file a `hydraflow-find`:
   - Title: `Un-cassetted adapter method: {Fake}.{method}`.
   - Body: method signature, suggested interaction shape for recording.
   - Labels: `hydraflow-find`, `fake-coverage-gap`.
5. Factory dispatches implementer; standard repair path records a new
   cassette against the real adapter and commits it.

**Escalation.** After 3 repair attempts, `hitl-escalation`,
`fake-coverage-stuck`.

**Five-checkpoint wiring**. Config `fake_coverage_auditor_interval`,
default `604800`.

### 4.8 RC wall-clock budget

**Purpose.** Catch the failure mode where the RC gate silently bloats.
A scenario suite that was 5 min in week 1 and 30 min in week 12
degrades RC cadence and delays every release.

**`RCBudgetLoop`** — `src/rc_budget_loop.py`, `BaseBackgroundLoop`.
Runs after each RC CI completion (watchdog cadence `14400`).

**On fire.**

1. Read the last 30 days of RC runs via `gh api`, extract per-run
   wall-clock duration. Separately read the most recent 5 runs for
   spike detection.
2. Compute rolling median (slow signal) **and** max of recent 5
   (fast signal). A single bad commit can jump duration 5× overnight;
   a median alone takes weeks to reflect that.
3. File a `hydraflow-find` if **either** threshold trips:
   - `current > rc_budget_threshold_ratio * rolling_median` (default
     `1.5`) — gradual bloat.
   - `current > rc_budget_spike_ratio * max(recent 5, excluding current)`
     (default `2.0`) — sudden spike.
   Issue body names which threshold tripped:
   - Title: `RC gate duration regression: {current_s}s vs {baseline}s {spike|median}`.
   - Body: per-job breakdown of the slow run, top-10 slowest tests,
     previous 5 runs for comparison, both threshold values.
   - Labels: `hydraflow-find`, `rc-duration-regression`.
4. Factory dispatches implementer; standard repair path identifies the
   bloat source — parallelization, test split, fixture optimization.

**Escalation.** After 3 repair attempts, `hitl-escalation`,
`rc-duration-stuck`.

**Five-checkpoint wiring**. Config `rc_budget_interval` default
`14400`; `rc_budget_threshold_ratio` default `1.5`.

### 4.9 Managed-repo wiki rot detector

**Purpose.** Keep per-repo wiki cites (`ADR-0032`) fresh. A wiki entry
citing `src/foo.py:some_func` that no longer exists degrades retrieval
quality for every agent query against that repo.

**`WikiRotDetectorLoop`** — `src/wiki_rot_detector_loop.py`,
`BaseBackgroundLoop`, weekly. Runs against HydraFlow-self's `repo_wiki/`
plus each managed repo's.

**On fire — per repo.**

1. Load `repo_wiki/<repo_slug>/*.md` entries via `src/repo_wiki.py:RepoWikiStore`.
2. For each entry, extract cited code references using a broader set
   of patterns (regex alone is insufficient):
   - `path/to/module.py:symbol` (file-colon-symbol, the house style)
   - `src.module.Class` and `src.module.function` (dotted import
     paths — some wiki entries use these)
   - Bare function/class names within fenced-code `python` blocks
     that look like cites (ambiguous; treat as hints not hard cites)
3. Verify each cite against the repo's HEAD by **AST introspection**,
   not grep: parse the module with `ast.parse`, walk for
   `FunctionDef`/`AsyncFunctionDef`/`ClassDef` definitions, and
   check symbol presence — catches re-exports, `__init__.py`
   re-bindings, and imports-as-public-API that grep misses. Fall
   back to grep for markdown files or non-Python cites (rare).
4. For each broken cite, file a `hydraflow-find`:
   - Title: `Wiki rot: {wiki_entry} cites missing {module}:{symbol}`.
   - Body: wiki entry excerpt, broken cite, suggested replacement from
     a fuzzy match against current symbol names in that module (if
     any).
   - Labels: `hydraflow-find`, `wiki-rot`.
5. Factory dispatches implementer or the existing wiki caretaker
   (`src/repo_wiki_loop.py` if that's the right home — plan picks);
   standard repair path updates the cite or removes the stale entry.

**Escalation.** After 3 repair attempts, `hitl-escalation`,
`wiki-rot-stuck`.

**Five-checkpoint wiring**. Config `wiki_rot_detector_interval`,
default `604800`.

### 4.10 Product-phase trust (Discover / Shape)

**Purpose.** Close the upstream half of the pipeline. HydraFlow routes
vague work through **Discover** (`src/discover_phase.py`,
`src/discover_runner.py:DiscoverRunner`) and **Shape**
(`src/shape_phase.py`, `src/shape_runner.py:ShapeRunner`) before Plan,
gated by `clarity_score` in `src/triage_phase.py`. Today these phases
have no adversarial gate — a prompt regression that produces shallow
discovery briefs or incoherent shape proposals is silently consumed by
the downstream Plan phase and propagates into bad code. For lights-off
autonomy, product-phase outputs must be gated the same way post-impl
outputs are.

**Depends on §4.1.** The corpus pattern (case directories, harness
parameterization, `expected_catcher.txt`, keyword assertion) is the
same; the evaluator skills are new.

**New evaluator skills** (registered in `src/skill_registry.py` the
same way post-impl skills are — `BUILTIN_SKILLS` list, phase-scoped).
Each is a prompt+parser pair matching the existing skill contract.
The rubrics below are the spec; the plan authors the exact prompt
text but must enforce these criteria.

- **`discover-completeness`** — evaluates a Discover brief. Returns
  RETRY if any of the following fails; RETRY reason must name which:
  - **Structure:** brief contains named sections for *Intent*,
    *Affected area*, *Acceptance criteria*, *Open questions*, *Known
    unknowns*. Missing section → RETRY keyword
    `missing-section:<name>`.
  - **Non-trivial content:** each section has ≥50 characters of prose
    (or ≥3 bulleted items for Acceptance criteria / Open questions).
    Short section → RETRY keyword `shallow-section:<name>`.
  - **No paraphrase-only:** at least one section adds information not
    present in the original issue body (evaluator compares the brief
    to the issue). Paraphrase-only → RETRY keyword `paraphrase-only`.
  - **Concrete acceptance criteria:** each bullet is testable —
    names an observable outcome, not a vague aspiration ("the app is
    faster" fails; "page-load p95 drops below 800ms" passes). Vague
    → RETRY keyword `vague-criterion`.
  - **Open questions exist when input is ambiguous:** if the brief
    claims zero open questions but the issue body contains
    ambiguity markers ("maybe", "could be", "not sure", "it depends"),
    RETRY with keyword `hid-ambiguity`.

- **`shape-coherence`** — evaluates a Shape proposal. Returns RETRY
  if any of the following fails:
  - **≥2 substantive options.** At least two options beyond
    "do nothing"; each has distinct scope. Fewer → RETRY keyword
    `too-few-options`.
  - **Do-nothing option present.** "Defer" / "no-op" / "accept
    status quo" is always one of the options. Missing → RETRY
    keyword `missing-defer`.
  - **Mutually exclusive scope.** Options must not overlap in the
    code areas they touch beyond a threshold (evaluator compares
    option scopes pairwise). Overlap > 50% → RETRY keyword
    `options-overlap`.
  - **Trade-offs named per option.** Each option lists at least one
    concrete cost/risk/trade-off. Missing → RETRY keyword
    `missing-tradeoffs`.
  - **Reconciles Discover ambiguities.** If the upstream Discover
    brief named open questions, the Shape proposal must address each
    (pick a position or explicitly punt with rationale). Un-addressed
    → RETRY keyword `dropped-discover-question`.

Both are lightweight prompt+parser skills following the `BUILTIN_SKILLS`
contract. Both return `RETRY` with a reason + keyword when the
evaluated output fails, matching the `expected_catcher.txt`
assertion pattern from §4.1.

**Corpus extension.** The `tests/trust/adversarial/cases/` directory
gains cases for these two skills using the existing layout:

- `before/` = synthetic upstream input (issue body + any prior phase
  output).
- `after/` = a deliberately bad Discover brief or Shape proposal.
- `expected_catcher.txt` = `discover-completeness` or `shape-coherence`.
- `README.md` = bug class + keyword.

v1 seed: ~8–12 cases covering at minimum:

- **Discover**: brief with missing acceptance criteria; brief that
  paraphrases the issue without new information; brief that names no
  open questions when the input is genuinely ambiguous.
- **Shape**: two options that overlap in scope; options without
  trade-off disclosures; proposal that skips the do-nothing option;
  proposal that fails to reconcile contradictions the Discover brief
  identified.

**Harness reuse.** `tests/trust/adversarial/test_adversarial_corpus.py`
(§4.1) parameterizes over every case in `cases/` and reads the
`expected_catcher` from `skill_registry`. The new skills register the
same way; no harness changes needed.

**CorpusLearningLoop reuse.** The v2 learning loop (§4.1) watches
`skill-escape`-labeled issues. When an escape is a product-phase
failure (bad Discover brief made it to Plan), the same synthesis
pipeline generates a new `discover-completeness` or `shape-coherence`
case. The loop is skill-agnostic — it reads the registry.

**Wiring.** No new loop for §4.10. Two new entries in
`BUILTIN_SKILLS`; extended invocation points in `DiscoverRunner` /
`ShapeRunner` to dispatch the evaluators after their respective
output is produced (same pattern `src/base_runner.py` uses for
post-impl skills at the end of implement phase).

**Dispatch timing.** Discover evaluates its brief before committing to
Shape; Shape evaluates its proposal before committing to Plan. On
RETRY, the runner loops (bounded by `max_discover_attempts` /
`max_shape_attempts` config — new fields, default 3) before
escalating with `hitl-escalation`, `discover-stuck` or `shape-stuck`.

**Fail-mode additions to §6.**

| Gate | Failure mode | Autonomous action | Blocks RC? | Escalates? | Label(s) |
|---|---|---|---|---|---|
| Discover evaluator | Brief fails `discover-completeness` | Runner retries | No (upstream of RC) | After 3 retries | `hitl-escalation`, `discover-stuck` |
| Shape evaluator | Proposal fails `shape-coherence` | Runner retries | No | After 3 retries | `hitl-escalation`, `shape-stuck` |
| Adversarial corpus (product phase) | Evaluator misses a case | Same as §4.1 | Yes | On retry exhaustion | `hydraflow-find`, `skill-regression` → `hitl-escalation`, `skill-repair-stuck` |

**Why fold into this spec rather than defer.** Discover and Shape are
the *design/product* phases of the lights-off factory. Without a
trust gate on their outputs, the dark factory cannot autonomously
process vague work — every bad brief would need a human to catch.
This is the first place autonomy fails without product-phase trust.
Same pattern, same harness, two new skills.

### 4.11 Factory cost & diagnostics waterfall

**Purpose.** A dark factory you can't see into is a factory you can't
operate. Before any scale beyond HydraFlow-self, operators must know
per issue: how many tokens were spent, what that cost in dollars, how
long the issue took end-to-end, and where the time and money went —
which phase, which skill, which subagent call, which loop. "Full
waterfall" on one screen in the Diagnostics tab.

**Current state — what already exists.** HydraFlow has substantial
telemetry already: `src/model_pricing.py:ModelPricing.estimate_cost`
(per-model input/output/cache token pricing),
`src/prompt_telemetry.py` (prompt-level tracking),
`src/trace_collector.py` (phase subprocess traces),
`src/factory_metrics.py`, `src/metrics_manager.py`, and diagnostics
routes `/overview`, `/tools`, `/skills`, `/subagents`,
`/cost-by-phase`, `/issues`, `/issue/{issue}/{phase}`. The data is
flowing. The gap is **one unified waterfall view per issue** plus
**per-loop telemetry** for the new trust loops this spec introduces.

**What this subsystem adds.**

1. **`/api/diagnostics/issue/{issue}/waterfall` endpoint** — a single
   call returning a rollup of one issue across every phase and
   sub-action. Shape:

   ```
   {
     "issue": 1234,
     "title": "...",
     "labels": [...],
     "total": {
       "tokens_in": 123456,
       "tokens_out": 45678,
       "cache_read_tokens": 234567,
       "cache_write_tokens": 7890,
       "cost_usd": 1.234,
       "wall_clock_seconds": 827,
       "first_seen": "...",
       "merged_at": "..."
     },
     "phases": [
       {
         "phase": "triage",
         "tokens_in": ..., "tokens_out": ..., "cost_usd": ...,
         "wall_clock_seconds": ...,
         "actions": [
           {"kind": "llm", "model": "sonnet-4-6", "tokens_in": ..., ...},
           {"kind": "skill", "skill": "diff-sanity", "tokens_in": ..., ...},
           {"kind": "subprocess", "command": "...", "duration_ms": ...},
           {"kind": "loop", "loop": "CorpusLearningLoop", "tokens_in": ..., ...}
         ]
       },
       {"phase": "discover", ...},
       {"phase": "shape", ...},
       {"phase": "plan", ...},
       {"phase": "implement", ...},
       {"phase": "review", ...},
       {"phase": "merge", ...}
     ]
   }
   ```

   Phases appear in execution order. Each phase's `actions` are ordered
   chronologically. Cost is computed on the fly from stored token
   counts via `ModelPricing.estimate_cost` so pricing-sheet updates
   retroactively re-price historical issues correctly.

2. **Diagnostics tab — Waterfall view.** `src/ui/src/` gains a
   "Waterfall" sub-tab under Diagnostics (or extends the existing
   per-issue drill-down view at `/issue/{issue}/{phase}`). Renders:
   - Top header: total tokens / cost / wall-clock / issue labels.
   - Stacked horizontal bar per phase, proportional to wall-clock
     duration, colored by phase.
   - Clicking a phase expands the actions list with per-action
     tokens/cost/duration.
   - Cost column sortable. "Top 10 expensive issues this week" link
     drills into the waterfall.

3. **Per-loop telemetry for trust loops.** Every new loop in this
   spec (`CorpusLearningLoop`, `ContractRefreshLoop`,
   `StagingBisectLoop`, `PrinciplesAuditLoop`, `FlakeTrackerLoop`,
   `SkillPromptEvalLoop`, `FakeCoverageAuditorLoop`, `RCBudgetLoop`,
   `WikiRotDetectorLoop`) must emit telemetry to
   `src/prompt_telemetry.py` when they call the LLM, and to
   `src/trace_collector.py` when they run subprocesses. Loop names
   appear as `{"kind": "loop", "loop": "<LoopClassName>"}` actions in
   the waterfall so operators see the full cost of the trust fleet,
   not just the pipeline.

4. **Aggregate rollups.** Extend the existing diagnostics router with:
   - `/api/diagnostics/cost/rolling-24h` — cost burned in last 24h,
     breakdown by phase + by loop.
   - `/api/diagnostics/cost/top-issues?range=7d&limit=10` — most
     expensive recent issues.
   - `/api/diagnostics/cost/by-loop?range=7d` — per-loop cost share,
     so `ContractRefreshLoop` recording against live services shows up
     as a line item, not hidden in telemetry.

5. **Per-loop cost dashboard (separate from the per-issue
   waterfall).** The waterfall is an *issue-level* view; operators
   also need a *machinery-level* view — what does it cost to **run
   the factory**, independent of any single issue? This is a
   distinct dashboard, not a sub-tab of the waterfall.

   **Endpoint**: `/api/diagnostics/loops/cost?range=7d|30d|90d`
   returning:

   ```
   {
     "range": "7d",
     "total": {
       "cost_usd": 42.18,
       "tokens_in": 5400000, "tokens_out": 800000,
       "llm_calls": 312,
       "wall_clock_seconds": 4860
     },
     "loops": [
       {
         "loop": "CorpusLearningLoop",
         "cost_usd": 8.42, "tokens_in": ..., "llm_calls": 47,
         "issues_filed": 3, "issues_closed": 2, "escalations": 0,
         "ticks": 52, "tick_cost_avg_usd": 0.16,
         "wall_clock_seconds": 840
       },
       {"loop": "ContractRefreshLoop", ...},
       {"loop": "StagingBisectLoop", ...},
       ... (all loops including existing pipeline loops)
     ]
   }
   ```

   **UI surface**: new "Factory Cost" dashboard tab (separate from
   Diagnostics/Waterfall):
   - Top-line: total machinery cost today / this week / this month.
   - Sortable per-loop table with all fields above plus sparkline of
     cost-per-day per loop (catches a loop that suddenly 10×'s its
     burn).
   - Highlight rows where `tick_cost_avg_usd` grew > 2× vs
     prior-period (a prompt regression that doubles token usage
     surfaces here before it burns the budget).
   - Coverage: **every** loop — the 5 pipeline loops (ADR-0001) and
     the 9 new trust loops in this spec and any existing caretaker
     loops (retrospective, report, sentry, etc.). Drop-downs filter
     by loop class.

   **Why separate from the issue waterfall:** issues are the
   factory's *output*; loops are the factory's *operating cost*. A
   loop that burns money without filing useful issues should stand
   out in the machinery view — in the issue view it would be diluted
   or invisible. Different questions, different screens.

5. **Cost budget alerts (lightweight).** Config fields
   `daily_cost_budget_usd` (default off) and
   `issue_cost_alert_usd` (default off). When set and crossed, a
   `hydraflow-find` issue with label `cost-budget-exceeded` fires.
   Not a blocker — an observability signal. Operators decide whether
   to tune, throttle, or approve. Matches §3.2: autonomous detection,
   operator in the loop only on exceptional conditions.

**What it does NOT add.** This subsystem does not introduce new
pricing logic, new telemetry capture, or parallel state stores. It
composes what exists into one view and ensures the new loops feed
into it. If `src/model_pricing.py` is missing a model, the plan adds
that model — but the pricing mechanism stays.

**Fail modes.**

| Gate | Failure mode | Autonomous action | Escalates? | Label(s) |
|---|---|---|---|---|
| Waterfall endpoint | Missing telemetry for a phase | Return partial rollup with `missing_phases` field; log at `warning` | No (observability, not correctness) | — |
| Cost budget | Daily cost exceeds `daily_cost_budget_usd` | File issue | No (operator signal) | `hydraflow-find`, `cost-budget-exceeded` |
| Issue cost | Single-issue cost exceeds `issue_cost_alert_usd` | File issue | No | `hydraflow-find`, `issue-cost-spike` |

**Testing.**

- Unit: `tests/test_diagnostics_waterfall.py` — waterfall endpoint
  against a fixture issue with recorded traces; asserts structure,
  phase ordering, cost totals match `ModelPricing`.
- MockWorld scenario: an issue runs through the full pipeline; the
  waterfall endpoint returns all seven phases in order with non-zero
  costs.
- Existing UI snapshot tests under `src/ui/` cover the new tab.

**Dependencies / prerequisites.**

- Existing telemetry infra listed above.
- Each new loop (§4.1–§4.10) must feed `prompt_telemetry` +
  `trace_collector`. Add this to each loop's implementation plan as a
  task.

**Why this goes in this spec and not a follow-on.** The trust fleet
and the pipeline will both burn tokens. A dark factory cannot be
operated — or even *decided to keep running* — without knowing what
it costs to do a unit of work. Observability and cost are
prerequisites to scaling beyond HydraFlow-self (goals 4, 7, 9, 10).

## 5. Shared infrastructure

**Directory tree:**

```
tests/trust/
├── __init__.py
├── adversarial/
│   ├── __init__.py
│   ├── test_adversarial_corpus.py
│   └── cases/
│       └── <case_name>/...
└── contracts/
    ├── __init__.py
    ├── test_fake_github_contract.py
    ├── test_fake_git_contract.py
    ├── test_fake_docker_contract.py
    ├── test_fake_llm_contract.py
    ├── cassettes/
    │   └── {github,git,docker}/*.yaml
    ├── claude_streams/*.jsonl
    └── fixtures/
        └── git_sandbox/
```

No `drills/` tree — rollback drills are out of scope (§2).

**`Makefile` targets** (added to the existing file):

- `make trust-adversarial` — runs `pytest tests/trust/adversarial/`.
- `make trust-contracts` — runs `pytest tests/trust/contracts/`.
- `make trust` — runs both, in order. Used by the RC workflow and
  locally.
- `make bisect-probe` — mirrors the RC gate's scenario command set
  (`make scenario && make scenario-loops` today). Used by
  `StagingBisectLoop`'s `git bisect run` so the probe and the gate
  cannot diverge (§4.3).
- `make audit` and `make audit-json` already exist (ADR-0044); no new
  target needed for `PrinciplesAuditLoop`.

**Loop-only caretakers** (§4.5–§4.9) are invoked through the standard
`BaseBackgroundLoop` dispatch, not via `make` targets — they have no
developer-facing CLI.

**CI wiring.** Add a new job `trust` to
`.github/workflows/rc-promotion-scenario.yml` that runs `make trust`.
Failing `trust` fails the RC promotion PR; per ADR-0042 the promotion
loop does not merge on red.

**Issue filing.** All three subsystems file `hydraflow-find` issues via
the existing `src/pr_manager.py:PRManager.create_issue` method. Do not
reinvent issue filing; do not introduce a parallel dedup layer —
`src/dedup_store.py:DedupStore` already provides idempotency.

## 6. Error handling & fail-mode table

Per §3.2, every row resolves to either **autonomous repair** or
**HITL escalation**; "waits for human review" is not a state.

Column "Blocks RC" means: does this specific failure mode red-fail the
RC promotion PR (and therefore block release)? "No" means the loop
files a signal and the factory repairs asynchronously. "No" is NOT
the same as "this failure is harmless" — correctness depends on the
repair landing in a reasonable window.

| Gate | Failure mode | Autonomous action | Red-fails RC? | Escalates? | Label(s) |
|---|---|---|---|---|---|
| `adversarial` corpus (RC gate) | Skill fails to flag a case | Standard CI-red retry; factory dispatches implementer against the failing skill | Yes | On retry exhaustion | `hydraflow-find`, `skill-regression` → `hitl-escalation`, `skill-repair-stuck` |
| `CorpusLearningLoop` | Synthesized case self-validation fails | Retry per escape issue | No | After 3× on same escape | `hitl-escalation`, `corpus-learning-stuck` |
| `contracts` replay (RC gate) | Fake output diverges from cassette | File `fake-drift`; factory dispatches implementer against `tests/scenarios/fakes/` | Yes | After 3 repair attempts | `hydraflow-find`, `fake-drift` → `hitl-escalation`, `fake-repair-stuck` |
| `ContractRefreshLoop` — cassette-only drift | Real output changed, fakes still green | Refresh PR auto-merges via standard reviewer + quality gates | No | Only if agent reviewer rejects the refresh PR 3× | — / `hitl-escalation`, `contract-refresh-stuck` |
| `ContractRefreshLoop` — cassette + fake drift | Real output changed, fakes broke | Refresh PR lands cassettes; companion `fake-drift` issue routes repair through implement phase | No (the drift itself is a warning signal; repair closes the loop) | After 3 implementer attempts | `hydraflow-find`, `fake-drift` → `hitl-escalation`, `fake-repair-stuck` |
| `ContractRefreshLoop` — stream-parser drift | Parser errors on fresh Claude stream | File `stream-protocol-drift`; factory repairs `src/stream_parser.py` | No | After 3 repair attempts | `hydraflow-find`, `stream-protocol-drift` → `hitl-escalation`, `stream-parser-stuck` |
| `StagingBisectLoop` — flake filter | Second `make scenario` passes | Log and exit; increment `flake_reruns_total` | No | No | — |
| `StagingBisectLoop` — confirmed red | Bisect identifies culprit | Auto-revert PR + retry issue; both auto-merge through standard gates | Yes (until revert merges) | No | `hydraflow-find`, `auto-revert`, `rc-red-attribution`, `rc-red-retry` |
| `StagingBisectLoop` — second revert needed | `auto_reverts_in_cycle > 0` | Stop reverting | Yes | Yes | `hitl-escalation`, `rc-red-bisect-exhausted` |
| `StagingBisectLoop` — revert conflict | `git revert` fails with conflicts | Abandon revert | Yes | Yes | `hitl-escalation`, `revert-conflict` |
| `StagingBisectLoop` — post-revert still red | New RC red after revert landed | Stop reverting; leave revert in place | Yes | Yes | `hitl-escalation`, `rc-red-post-revert-red` |
| `StagingBisectLoop` — watchdog timeout | No green RC within 2 cycles / 8h | Stop waiting | Yes | Yes | `hitl-escalation`, `rc-red-verify-timeout` |
| `StagingBisectLoop` — harness failure | Bisect itself errors | Log at warning | No (unrelated to regression) | Yes | `hitl-escalation`, `bisect-harness-failure` |
| `StagingBisectLoop` — invalid bisect range | `last_green_rc_sha` unreachable (rebase) | Skip with warning log | No | No (idempotent no-op) | — |
| `PrinciplesAuditLoop` — STRUCTURAL/BEHAVIORAL regression | Check_id went PASS → FAIL | File `principles-drift`; factory repairs | No (weekly detector, not RC gate) | After 3 repair attempts | `hydraflow-find`, `principles-drift` → `hitl-escalation`, `principles-stuck` |
| `PrinciplesAuditLoop` — CULTURAL regression | Check_id went PASS → FAIL on a CULTURAL row | File `principles-drift` | No | Immediately (1 failed attempt) | `hitl-escalation`, `principles-stuck`, `cultural-check` |
| `PrinciplesAuditLoop` — onboarding | New managed repo has P1–P5 FAILs | File `onboarding-blocked`; factory scaffolds | Blocks trust-subsystem install on that repo | After 3 scaffolding attempts | `hydraflow-find`, `onboarding-blocked` → `hitl-escalation`, `onboarding-stuck` |
| `FlakeTrackerLoop` | Test crosses flake threshold | File `flaky-test`; factory repairs | No | After 3 repair attempts | `hydraflow-find`, `flaky-test` → `hitl-escalation`, `flaky-test-stuck` |
| `SkillPromptEvalLoop` | Corpus case regressed PASS → FAIL | File `skill-prompt-drift`; factory repairs | No | After 3 repair attempts | `hydraflow-find`, `skill-prompt-drift` → `hitl-escalation`, `skill-prompt-stuck` |
| `FakeCoverageAuditorLoop` | Un-cassetted adapter method found | File `fake-coverage-gap`; factory records cassette | No | After 3 repair attempts | `hydraflow-find`, `fake-coverage-gap` → `hitl-escalation`, `fake-coverage-stuck` |
| `RCBudgetLoop` | RC duration > threshold × rolling median | File `rc-duration-regression`; factory optimizes | No | After 3 repair attempts | `hydraflow-find`, `rc-duration-regression` → `hitl-escalation`, `rc-duration-stuck` |
| `WikiRotDetectorLoop` | Broken `module:symbol` cite in wiki | File `wiki-rot`; factory fixes cite | No | After 3 repair attempts | `hydraflow-find`, `wiki-rot` → `hitl-escalation`, `wiki-rot-stuck` |

## 7. Testing — how we test the trust-hardening itself

The harnesses under `tests/trust/` are the *gate runners*. They need
their own unit tests, separately, so a bug in a gate runner surfaces
through the normal `make test` path rather than through a silent
false-negative on the RC.

**Unit tests (under `tests/`, not `tests/trust/`):**

- `tests/test_adversarial_corpus_harness.py` — harness parameterization,
  case-directory parsing, `expected_catcher.txt` validation, keyword
  assertion. Run against synthetic fake cases, not the real corpus.
- `tests/test_contract_cassette_schema.py` — cassette YAML schema
  validation, normalizer application.
- `tests/test_contract_replay_harness.py` — replay harness behavior on
  synthetic cassette + synthetic fake.
- `tests/test_staging_bisect_loop.py` — loop behavior with a `FakeGit`
  that fakes the bisect process; covers the idempotency path, the
  invalid-range skip, and the harness-failure path.
- `tests/test_corpus_learning_loop.py` — escape-signal detection,
  synthesis dispatch (mocked), PR opening (mocked).
- `tests/test_contract_refresh_loop.py` — refresh-and-PR flow (mocked
  external CLIs).
- `tests/test_principles_audit_loop.py` — audit diff (pass/fail set),
  onboarding-gate logic, STRUCTURAL vs CULTURAL escalation paths.
- `tests/test_flake_tracker_loop.py` — flake-count accumulation, threshold
  breach, issue filing. Mock `gh api` run query.
- `tests/test_skill_prompt_eval_loop.py` — corpus regression detection
  against a fixture snapshot.
- `tests/test_fake_coverage_auditor_loop.py` — AST introspection of
  fake classes, cassette parsing, coverage gap computation.
- `tests/test_rc_budget_loop.py` — rolling-median computation,
  threshold-ratio breach, fixture of 30 mocked runs.
- `tests/test_wiki_rot_detector_loop.py` — cite extraction via regex,
  verification against fixture repo, fuzzy-match suggestion.

**Loop-wiring completeness.** `tests/test_loop_wiring_completeness.py`
(existing) must gain entries for all nine new loops:
`CorpusLearningLoop`, `ContractRefreshLoop`, `StagingBisectLoop`,
`PrinciplesAuditLoop`, `FlakeTrackerLoop`, `SkillPromptEvalLoop`,
`FakeCoverageAuditorLoop`, `RCBudgetLoop`, `WikiRotDetectorLoop`. All
five checkpoints per loop; missing any entry is a hard test failure
per `docs/agents/background-loops.md`.

**End-to-end per subsystem (gate-side).**

- `tests/trust/adversarial/test_adversarial_corpus.py` runs against the
  committed seed corpus. Synthetic **good** inputs — a case deliberately
  designed **not** to trip any skill — live alongside the regular cases,
  flagged in `expected_catcher.txt` with the sentinel `none`, and are
  asserted to pass through all four skills without a RETRY.
- `tests/trust/contracts/` includes at least one cassette per adapter in
  the initial commit, so the replay path is exercised from day one.
- `tests/test_staging_bisect_loop.py` includes an E2E variant that
  drives a three-commit fixture repo end-to-end through the bisect,
  asserting the correct culprit is identified and the issue title
  matches.

**MockWorld scenarios (loop-side) — required.** Each new loop
introduced by this spec (`CorpusLearningLoop`, `ContractRefreshLoop`,
`StagingBisectLoop`, `PrinciplesAuditLoop`, `FlakeTrackerLoop`,
`SkillPromptEvalLoop`, `FakeCoverageAuditorLoop`, `RCBudgetLoop`,
`WikiRotDetectorLoop`) must land with a MockWorld scenario under
`tests/scenarios/` that exercises its pipeline behavior end-to-end
using stateful fakes. A scenario:

1. Seeds `MockWorld` with the trigger state (e.g. a scripted RC-red
   for `StagingBisectLoop`, a `skill-escape`-labeled issue for
   `CorpusLearningLoop`, a broken cite in `repo_wiki/` for
   `WikiRotDetectorLoop`).
2. Advances `FakeClock` past the loop's interval.
3. Runs the pipeline via `world.run_pipeline()` or the loop-specific
   scenario marker (`scenario_loops` per the existing `MockWorld`
   conventions in `tests/scenarios/conftest.py`).
4. Asserts on the world's final state: the expected `hydraflow-find`
   issue was filed with the right labels, the expected PR was opened
   against `staging`, the expected scripted-CI consumption happened,
   the retry issue was filed where applicable.

**Why the split between `tests/trust/` and `tests/scenarios/`.** The
gate harnesses in `tests/trust/` validate the real dependencies
MockWorld relies on (real skills catch real bad diffs, fakes match
real services). The MockWorld scenarios validate that the loops, when
wired into the factory, drive the pipeline correctly using those
already-validated dependencies. Running the adversarial corpus through
`FakeLLM` would be asserting that the fake pretends to catch the bad
diff, which defeats the gate; running `StagingBisectLoop` without
MockWorld would miss the pipeline integration — retry issue → factory
picks up → implement phase runs. Both layers are required; they test
different invariants.

## 8. Dependencies / prerequisites

**Existing, already in the tree.**

- `src/base_background_loop.py:BaseBackgroundLoop` — loop base class.
- `src/staging_promotion_loop.py:StagingPromotionLoop` — subsystem §4.3
  hooks here.
- `src/pr_manager.py:PRManager.create_issue` — issue filing.
- `src/dedup_store.py:DedupStore` — idempotency.
- `src/state/__init__.py:StateTracker` — `last_green_rc_sha` read
  (subsystem §4.3).
- `src/base_runner.py` — skill dispatch path (subsystem §4.1 harness).
- `src/diff_sanity.py`, `src/scope_check.py`, `src/test_adequacy.py`,
  `src/plan_compliance.py` — the four post-impl skills under test.
- `src/stream_parser.py` — Claude-stream parser (subsystem §4.2
  replay side for `FakeLLM`).
- `tests/test_loop_wiring_completeness.py` — existing wiring enforcer.

**Prerequisite the plan must add.**

- `src/staging_promotion_loop.py:StagingPromotionLoop` does not today
  emit an `rc_red` event — it files a `hydraflow-find` issue directly
  in `_handle_open_promotion`. The subsystem §4.3 plan must add an
  event emission (the plan picks the mechanism: new method on the loop
  that `StagingBisectLoop` can subscribe to, a shared event bus, or —
  simplest — a state-tracker field `last_rc_red_sha` that
  `StagingBisectLoop` polls). This is a small surface addition, not a
  refactor; call it out as a prerequisite in the subsystem §4.3 plan's
  first task.
- `last_green_rc_sha` is not persisted today. The subsystem §4.3 plan
  must add a write to `StateTracker` from `StagingPromotionLoop` on
  each successful promotion (the `"status": "promoted"` return path in
  `_handle_open_promotion`).

**Out-of-tree dependencies.**

- `gh` CLI, `git`, `docker` must be available in the RC workflow
  environment (already true — the existing scenario job uses `gh` and
  `git`; `docker` is present on GitHub-hosted runners).
- Test-scoped GitHub repo for `FakeGitHub` cassettes. The refresh loop
  requires a throwaway repo. The subsystem §4.2 plan must specify
  which (options: a dedicated `hydraflow-contracts-sandbox` repo
  under the HydraFlow GitHub org, or an ephemeral fork spun up by the
  loop).

## 9. Open questions / deferred decisions

1. **Cassette rotation cadence.** Weekly default in §4.2. `gh` CLI is
   stable enough that weekly may be noisy; monthly is plausible.
   Revisit after the first two refresh cycles.
2. **Learning-loop v2 escape-signal source.** Three options:
   - **Default:** a dedicated `skill-escape` label added to
     `hydraflow-find` issues when a human identifies a PR bug that
     should have been caught. Explicit, low false-positive.
   - Generic `hydraflow-find` label without `skill-escape`. Too noisy
     — catches non-skill issues.
   - Reverted-commit detection (watch for `Revert "..."` merges to
     `main`). Catches cases humans forget to label but false-positives
     on intentional reverts.
   Ship with `skill-escape` as the default; leave a config knob
   `corpus_learning_signal_label` so the decision can flip without a
   code change.
3. **Corpus size budget.** When do we prune old cases that a skill has
   never regressed on? TBD. Default: **grow forever in v1**. Revisit
   if the corpus crosses 200 cases or the gate runtime crosses 5
   minutes.
4. **Stream-sample prompt stability.** The Claude stream sample uses a
   short, stable prompt so repeated recordings compare. The subsystem
   §4.2 plan picks the exact prompt. Revisit if Anthropic changes
   stream-json schema in a way that invalidates committed samples.
5. **Bisect runtime cap.** `make scenario` currently takes ~5 minutes.
   A bisect over 16 commits is ~20 minutes. Above some threshold the
   bisect is more disruptive than useful. TBD — the plan specifies a
   runtime cap (default suggestion: 45 minutes; skip with a warning
   beyond that).

## 10. Related

- `ADR-0001` — Five concurrent async loops (context for existing loop
  count; the three new loops here are `BaseBackgroundLoop` auxiliaries,
  not pipeline loops).
- `ADR-0022` — MockWorld integration-test architecture. Subsystem §4.2
  guards the fakes this ADR introduced.
- `ADR-0029` — Caretaker loop pattern. All three new loops follow it.
- `ADR-0042` — Two-tier branch model + RC promotion. The promotion PR
  is where §4.1 v1 and §4.2 replay gates land.
- `ADR-0044` — HydraFlow Principles. P3 (testing rings, MockWorld), P5
  (CI and branch protection), P8 (superpowers skills) are load-bearing
  here; the audit table rows these checks map to live in that ADR.

## 11. Scope: HydraFlow-self today, managed repos later

### 11.1 Principles as foundation (load-bearing)

This entire initiative rests on `ADR-0044` HydraFlow Principles being
**in place and enforced**. These gates are not freestanding "good
ideas" — they are the concrete guardrails that presuppose a specific
repository shape:

- The adversarial skill corpus (§4.1) presupposes **P3** — the
  post-impl skill chain exists and is dispatched through a known
  registry.
- The contract tests (§4.2) presuppose **P3** — stateful `MockWorld`
  fakes exist under `tests/scenarios/fakes/` that real adapters can
  be diffed against.
- The staging-red bisect (§4.3) presupposes **P4/P5** plus
  `ADR-0042` — branch protection, CI mirroring local gates, a
  two-tier branch model with an RC promotion PR.
- Every subsystem presupposes **P1** (documentation contract) so the
  filed `hydraflow-find` issues have a knowable structure, **P8**
  (skills integration) so the repair-side implement phase has a
  working agent toolchain, and **P9** (persistence layout) so
  caretaker state is stored under a predictable root.

Without these in place, the trust subsystems have nothing to stand
on. Shipping them to a repo that fails `make audit` is cargo-cult
trust — the gate runs but guards a shape that does not exist.

**Today this is enforced by convention, not mechanism.** `make audit`
(`scripts/hydraflow_audit/`) measures conformance; `make init`
(`scripts/hydraflow_init/`) scaffolds missing pieces for greenfield
adoption. Neither is wired as a hard gate: no CI job fails on audit
regression, no onboarding flow refuses to manage a non-conformant
target repo, no caretaker detects principle drift over time. See
§11.3 for the drift detector this initiative adds to the named
follow-on caretaker list.

### 11.2 Per-subsystem extension path

**Today (v1).** Every subsystem in this spec operates on HydraFlow's
own repository: the adversarial corpus tests HydraFlow's own skill
chain, the contract tests guard HydraFlow's own fakes, the bisect loop
watches HydraFlow's own RC promotion. This matches `ADR-0042`'s
negative consequence ("Single-repo scope today; revisit when the
multi-repo factory lands").

**Tomorrow.** HydraFlow's goal is to build and maintain **real
software**, not just itself. As the factory scales to N managed
target repos, the trust architecture must follow — **but only for
repos that pass `make audit` first**. Each subsystem has a per-repo
extension path, with principle conformance as the gate:

| Subsystem | Per-managed-repo extension | Notes |
|---|---|---|
| Adversarial skill corpus (§4.1) | Each managed repo gets its own corpus under its repo slug (e.g. `tests/trust/adversarial/cases/<repo_slug>/`), plus a shared-core corpus for universal bug classes (syntax errors, missing tests, scope creep) | The harness reads the skill registry; no spec change needed to onboard a new repo's corpus |
| Contract tests (§4.2) | Fakes live in HydraFlow (they simulate HydraFlow's adapters), so a single contract suite covers all managed repos. One cassette set is enough | The `ContractRefreshLoop` remains a single caretaker |
| Staging-red bisect (§4.3) | Per managed repo that adopts `ADR-0042`'s two-tier model. The loop runs N instances (one per repo with a staging branch), each bisecting that repo's own promotion | Requires per-repo `last_green_rc_sha` state keys; straightforward with current `StateTracker` repo-slug scoping (`ADR-0021` P9) |

### 11.3 The caretaker fleet — compounding trust over time (see §12 for operability)

The nine subsystems in §4 are this spec's trust fleet. §4.1–§4.3 are
primary RC-boundary gates; §4.4 is the foundational principles
enforcer that everything else rests on; §4.5–§4.9 are caretakers that
compound trust over time by watching narrower failure modes (flakes,
prompt drift, cassette coverage, RC duration, wiki rot).

**Implementation priority.**

1. **§4.4 PrinciplesAuditLoop first** — nothing else guards anything
   without it (§11.1).
2. **§4.1–§4.3 primary gates next** — they close the largest
   observable gaps.
3. **§4.5–§4.9 caretakers last** — they compound on top of the
   primary gates' outputs (e.g., `SkillPromptEvalLoop` reuses the
   corpus §4.1 creates; `FakeCoverageAuditorLoop` reuses the
   cassettes §4.2 creates).

**Future caretakers beyond this spec.** The nine here cover every
failure mode this spec's authors can currently name. When new ones
emerge — almost certainly from production incident retrospectives —
each follows the same pattern: a `BaseBackgroundLoop` subclass,
five-checkpoint wiring, autonomous repair via `hydraflow-find`,
escalation on 3-attempt failure per §3.2. The pattern compounds; the
fleet grows.

## 12. Operability — watching the watchers, pausing the loops, measuring success

Autonomy without observability is a black box you can't safely run.
This section defines the operator contract for the trust fleet:
what operators see, how they intervene, and how we measure whether
the whole thing works.

### 12.1 Meta-observability — loops watching loops

§4.11 gives the per-loop cost dashboard. §12 adds the per-loop
**behavior** view: what did each loop *do*, not just what did it
*cost*. Endpoint: `/api/trust/fleet?range=7d|30d`.

Per loop:
- `ticks_total`, `ticks_errored` (tick exit non-zero), `last_tick_at`.
- `issues_filed_total`, `issues_closed_total`, `issues_open_escalated`.
- `repair_attempts_total`, `repair_successes_total`,
  `repair_failures_total`.
- Loop-specific: `reverts_merged` (bisect), `cases_added` (learning),
  `cassettes_refreshed` (contract), `principles_regressions`
  (audit), etc.

**Trust-loop sanity caretaker.** A new tenth loop,
**`TrustFleetSanityLoop`** (`src/trust_fleet_sanity_loop.py`), watches
the above metrics. Who watches the watchers — the watchers watch each
other. On any of the following anomalies, it files a
`hitl-escalation` issue with label `trust-loop-anomaly`:

- A loop files > `loop_anomaly_issues_per_hour` (default 10) issues
  in an hour.
- A loop's `repair_failures_total` over 24h exceeds
  `repair_successes_total` × 2 — it's churning, not fixing.
- A loop's `ticks_errored / ticks_total` ratio exceeds 0.2 over the
  last 24h — it's broken.
- A loop hasn't ticked in > `loop_staleness_s` (default 2 ×
  interval) and is `enabled` — its scheduler dropped it.
- A loop's cost spikes > 5× its 30-day median (this reads from
  §4.11).

The sanity loop itself is watched by **inverted self-check**: if
`TrustFleetSanityLoop` stops ticking, the existing `HealthMonitor`
(`src/health_monitor.py`) detects it and files a conventional health
issue. This breaks the recursion at the health layer — health is the
root of trust; without it, the operator has nothing to stand on.

`TrustFleetSanityLoop` follows the same five-checkpoint wiring. Add
to `tests/test_loop_wiring_completeness.py`. Adds Loop #10 to the
§4 subsystem count.

### 12.2 Kill-switch / pause contract

Every loop in §4 and §12.1 must honor a `<loop_name>_enabled` config
field (default `True`). When `False`, the loop's tick returns
immediately; its state is preserved; no issues are filed. Operators
flip this via the dashboard's System tab (existing surface) when a
loop misbehaves. This is load-bearing for operability — a loop bug
that creates 100 revert PRs per hour must have a faster stop than
"ship a fix through the pipeline."

Consistent naming:
- `corpus_learning_enabled`
- `contract_refresh_enabled`
- `staging_bisect_enabled`
- `principles_audit_enabled`
- `flake_tracker_enabled`
- `skill_prompt_eval_enabled`
- `fake_coverage_auditor_enabled`
- `rc_budget_enabled`
- `wiki_rot_detector_enabled`
- `trust_fleet_sanity_enabled`

Env overrides follow the existing `HYDRAFLOW_*_ENABLED` pattern.

### 12.3 Dashboard surfaces — the operator's trust panel

The existing Diagnostics tab is the anchor. This spec adds three
companion panels:

- **Factory Cost** (§4.11) — per-issue waterfall + per-loop cost
  dashboard.
- **Trust Fleet** (§12.1) — per-loop behavior metrics, kill switches,
  recent escalations, anomaly indicator.
- **Principles** (§4.4) — current audit status for HydraFlow-self and
  every managed repo, regression history, last-audit timestamp.

All three panels read from existing persistence (`StateTracker`,
`trace_collector`, `prompt_telemetry`) via new read-only endpoints
under `/api/trust/*` and `/api/diagnostics/*`. No new stores.

### 12.4 Success metrics — what "working" looks like

Qualitative "lights-off" needs quantitative targets. Baseline-then-
target mapping after the spec lands:

**30-day targets** (measured on HydraFlow-self):
- **Skill escape rate**: zero bugs merged to `main` that the
  adversarial corpus *could* have caught (a post-hoc review, logged
  in a monthly retro). The number is zero because every caught
  escape should have gone through `CorpusLearningLoop` → new case.
- **Fake drift**: all four adapters have a refresh PR cycle completed
  successfully at least twice — proves the `ContractRefreshLoop` is
  closing loops end-to-end.
- **RC-red MTTR** (time from red RC detected → green RC): p50 < 2h
  (auto-revert + retry cycle), p95 < 8h (watchdog cap). Before this
  spec: indeterminate / manual.
- **Principles conformance**: zero regressions on P1–P5 unfixed for
  more than 24h.

**90-day targets**:
- **HITL escalation rate**: < 3 per week across the fleet. Above that
  means autonomy isn't holding; the escalations need design-level
  fixes, not just case-by-case handling.
- **Factory burn rate**: defined and trending — operators can answer
  "what does an issue cost" from the Waterfall in < 30 seconds, and
  "what does the machinery cost per day" from Factory Cost in < 10
  seconds.
- **Cross-repo readiness**: at least one target repo beyond
  HydraFlow-self has passed `PrinciplesAuditLoop` onboarding and
  received all applicable trust subsystems.

Targets are aspirational and written into a monthly retro doc
(`docs/retros/YYYY-MM-trust-fleet.md`). Missed targets are not
failures — they are inputs to the next spec iteration. The
`RetrospectiveLoop` (existing) automates retro scaffolding; the
targets become queryable from the `/api/trust/fleet` endpoint so
retros are data-driven.

### 12.5 Escalation lifecycle — closing the operator loop

Reiterating §3.2 for explicit operational clarity. Every
`hitl-escalation` issue:

1. Loop files it.
2. Human sees it via the Trust Fleet panel (§12.3) alert or the
   normal issue queue.
3. Human closes it (with or without a merged fix).
4. On close, the associated dedup key in
   `src/dedup_store.py:DedupStore` clears — the loop is free to
   re-fire on the *next* drift. State is never sticky past a close.

This close→clear mechanism must be unit-tested per loop. Without it
a closed escalation silently muzzles the loop forever.
