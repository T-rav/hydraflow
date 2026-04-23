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

This stance overrides individual subsystem descriptions. If §4.1–§4.3
appear to describe a human gate anywhere on the happy path, that is a
drafting bug — treat §3.2 as authoritative and auto-merge with
guardrails.

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
   scenario suite once against the RC PR's head. If the second run
   passes, the red was a flake; log at `warning`, increment a
   `flake_reruns_total` counter in state, and exit. No bisect, no
   revert.
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
4. **Safety guardrail.** `StateTracker` tracks `rc_cycle_id` and
   `auto_reverts_in_cycle` (count). If `auto_reverts_in_cycle > 0`,
   **do not revert again.** A second red after a first revert means
   either the bisect was wrong or the damage is broader than one PR —
   escalate: file `hitl-escalation`, `rc-red-bisect-exhausted` with
   both bisect logs and stop. Reset the counter only when a green RC
   promotes.
5. **Revert PR.** Create branch
   `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}` off `staging`. Run
   `git revert <culprit_sha>` for a single commit, or
   `git revert -m 1 <merge_sha>` for a merge commit. Push. Open PR
   against `staging` via `src/pr_manager.py:PRManager`:
   - Title: `Auto-revert: PR #{N} — RC-red attribution on <test_name>`
   - Body: culprit SHA, failing scenario test names, RC PR URL,
     `git show <sha> --stat`, bisect log, link to the retry issue
     (step 6).
   - Labels: `hydraflow-find`, `auto-revert`, `rc-red-attribution`.
6. **Retry issue.** Simultaneously file a new `hydraflow-find` issue
   via `src/pr_manager.py:PRManager.create_issue`:
   - Title: `Retry: <original PR title>`
   - Body: link to the reverted PR, full bisect log, failing test
     names, time bounds (start SHA → end SHA → duration).
   - Labels: `hydraflow-find`, `rc-red-retry`. The standard pipeline
     picks up `hydraflow-find` issues; the factory re-does the work.
7. **Auto-merge path (per §3.2).** The revert PR flows through the
   standard agent-reviewer + quality-gate + auto-merge path. The
   retry issue flows through the standard implement/review pipeline.
   No human approval on either happy path.
8. **Outcome verification.** After the revert merges, the next
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
9. **Cleanup.** `git worktree remove --force` on the bisect worktree
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

**Onboarding gate.** When a new target repo is registered with the
factory (plan picks the signal — new `managed_repos` config entry,
new registration API, or a label on a `hydraflow-onboard` issue):

- Before the factory installs any trust subsystem (§4.1–§4.3, §4.5–§4.9)
  against the new repo, the loop runs `make audit --json` and reads
  the result.
- **P1–P5 FAILs block onboarding.** These are load-bearing
  (documentation contract, layers, testing rings, quality gates, CI +
  branch protection). File a `hydraflow-find` issue labeled
  `onboarding-blocked` naming the failing checks. Factory dispatches
  the implementer to remediate (or routes to `make init` for
  greenfield scaffolding). The repo does not receive trust
  subsystems until P1–P5 go green.
- **P6–P10 FAILs warn but do not block.** P6 (loops/labels) is
  optional for non-orchestration repos; P7–P10 are high-value but
  not structurally required for the trust gates to function.

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
   AST (`ast.parse` on the file; read public methods — those not
   prefixed `_`).
2. Parse all cassettes under `tests/trust/contracts/cassettes/<adapter>/`
   and collect the real-adapter method invoked by each (`input.command`
   is the source of truth).
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
   wall-clock duration.
2. Compute rolling median.
3. If current run exceeds `rc_budget_threshold_ratio * median`
   (default `1.5`), file a `hydraflow-find`:
   - Title: `RC gate duration regression: {current_s}s vs {median_s}s median`.
   - Body: per-job breakdown of the slow run, top-10 slowest tests,
     previous 5 runs for comparison.
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
2. For each entry, extract cited `module:symbol` references (pattern:
   `\b([a-zA-Z_/.]+\.py):([a-zA-Z_][a-zA-Z0-9_]*)`).
3. Verify each cite against the repo's HEAD — the file exists and the
   symbol is defined (grep for `def symbol|class symbol`).
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

| Gate | Failure mode | Autonomous action | Blocks RC until fix? | Escalates? | Label(s) |
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

### 11.3 The caretaker fleet — compounding trust over time

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
