# Sandbox-tier scenarios

End-to-end Tier-2 scenario tests that boot the real HydraFlow stack
inside Docker (per `docker-compose.sandbox.yml`) with MockWorld swapped
at the boundary, drive the UI via Playwright, and verify behavior
without external network access.

See ADR-0052 (`docs/adr/0052-sandbox-tier-scenarios.md`) for the
architecture, and the spec at
`docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md`.

## Adding a scenario

1. Create `scenarios/sNN_my_scenario.py` with:
   - `NAME` — stable identifier (matches filename minus `.py`)
   - `DESCRIPTION` — one-line summary
   - `seed() -> MockWorldSeed` — pure function returning the initial state
   - `async assert_outcome(api, page) -> None` — runs after the loop has
     ticked; asserts via REST (`api`) and Playwright (`page`)

2. Run host-side parity test:

   ```
   .venv/bin/pytest tests/scenarios/test_sandbox_parity.py -v
   ```

   Confirms the seed is well-formed and apply_seed succeeds in-process.

3. Run end-to-end via the harness:

   ```
   python scripts/sandbox_scenario.py run sNN_my_scenario
   ```

   Builds the compose stack, boots, runs your assertions, tears down.
   Returns 0 on PASS, 1 on scenario failure, 2 on infra failure.

## MockWorld fidelity rules

MockWorld scenarios should exercise production ports through fake adapters
whenever the adapter exists. For GitHub side effects, prefer the default
`FakeGitHub` wired into `MockWorld` and assert on stored issues, labels,
comments, PRs, and CI scripts. Do not replace `pr_manager.create_issue`,
`post_comment`, or `add_labels` with a raw `AsyncMock` just to count calls; that
misses the fake-adapter contract and can hide title/body/label drift.

Patch only the true external boundary that MockWorld cannot yet model, such as
`gh run download`, `git bisect`, or an LLM/subprocess corpus runner. When a loop
has enrichment logic behind that boundary, add focused unit coverage for the
parser/formatter as well as the scenario. The RC budget loop is the reference
pattern: the MockWorld scenario asserts issue creation through `FakeGitHub`,
while unit tests cover job-breakdown parsing, JUnit parsing, and issue-body
enrichment without creating live GitHub issues.

## Existing scenarios

| Name | What it tests |
|------|---------------|
| s00_smoke | Trivial parity-only — proves wiring works |
| s01_happy_single_issue | Single issue → triage → plan → implement → review → merge |
| s02_batch_three_issues | 3 issues progress in parallel |
| s03_review_retry_then_pass | Review fails attempt 1, passes attempt 2 |
| s04_ci_red_then_fixed | PR with red CI → ci-fix runner → green CI → merged |
| s05_hitl_after_review_exhaustion | 3 review failures → HITL surfaces |
| s06_kill_switch_via_ui | UI toggle disables loop → no further ticks |
| s08_pr_unsticker_revives_stuck_pr | Stale PR → auto-resync triggers |
| s09_dependabot_auto_merge | Dependabot PR + green CI → auto-merged |
| s12_trust_fleet_three_repos_independent | 3 repos process independently |
| s15_ci_monitor_main_branch_red | Main-branch CI failure is detected and surfaced |
| s54_decompose_to_converge | Auto-agent-exhausted stall decomposes into children; children ship via the light lane |
| s55_nested_decompose | Depth-2 nested decompose; leaf children ship via the light lane; root epic converges |
| s93_light_lane_single_spawn | Complexity-2 issue → light lane → one scripted auto-agent spawn → PR → merged (no plan/implement, no human) |
| s_advisor_full_loop | Advisor loop runs through full review feedback flow |

## CI

The sandbox-{fast,full,nightly} CI jobs run scenarios at 3 cadences:
- **fast** (PR→staging): s01_happy_single_issue, s06_kill_switch_via_ui, s53_model_routing_settings_ui, s54_decompose_to_converge, s55_nested_decompose, s58_work_queue_settings_ui, s59_queue_strategy_board_badge, s91_gateway_session_tap
- **full** (rc/* promotion PR): all scenarios, sharded 6 ways, with auto-fix label routing on failure
- **nightly** (03:00 UTC schedule): all scenarios, opens hydraflow-find issue on failure

The fast list above is the one `.github/workflows/ci.yml` actually runs;
`tests/architecture/test_sandbox_ci_cache.py` fails if this line, the
`sandbox-fast` job, and the `Sandbox Scenario (dispatch)` workflow drift apart.
Full module names deliberately — the guard compares them to the workflow's
`for s in …` list, which short forms like "s01, s06" cannot be checked against.
It said "s01, s06 only" for six scenarios longer than it was true (#11601).

## Running a verification

Local `docker compose` runs are for **developing** a scenario — the fast
edit/run loop, `python scripts/sandbox_scenario.py shell`, poking the stack by
hand. They are not for **verifying** one: the factory host is a single machine
driving the whole pipeline, and a compose stack on it during production hours
competes with the factory for the resource it needs most.

To verify a scenario, dispatch the **Sandbox Scenario (dispatch)** workflow
(`.github/workflows/sandbox-dispatch.yml`) instead — it runs on a GitHub
runner and prints the PASS/FAIL tail into the job summary:

```
gh workflow run "Sandbox Scenario (dispatch)" --ref my-branch -f ref=my-branch -f scenario=s01_happy_single_issue
```

`--ref` selects the branch that is actually checked out; the `ref` input
restates it and the job fails fast if the two disagree. Both are needed on
purpose: checking out a branch named by an *input* while the run sits on
another branch is a cache-poisoning shape (CodeQL
`actions/cache-poisoning/poisonable-step`), so the run's own ref is the one
verified and the input is only an assertion of intent. `scenario` takes a
scenario name, `fast`, or `all`.

See `docs/wiki/testing.md` → "Sandbox verification runs belong in CI, not on
the factory host".
