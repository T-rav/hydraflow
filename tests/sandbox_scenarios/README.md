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

## Existing scenarios

| Name | What it tests |
|------|---------------|
| s00_smoke | Trivial parity-only — proves wiring works |
| s01_happy_single_issue | Single issue → triage → plan → implement → review → merge |
| s02_batch_three_issues | 3 issues progress in parallel |
| s03_review_retry_then_pass | Review fails attempt 1, passes attempt 2 |
| s04_ci_red_then_fixed | PR with red CI → ci-fix runner → green CI → merged |
| s05_hitl_after_review_exhaustion | 3 review failures → HITL surfaces |
| s08_pr_unsticker_revives_stuck_pr | Stale PR → auto-resync triggers |
| s09_dependabot_auto_merge | Dependabot PR + green CI → auto-merged |
| s12_trust_fleet_three_repos_independent | 3 repos process independently |
| s15-s41 | Additional runnable loop-specific smoke and recovery scenarios |
| s_advisor_full_loop | Advisor full-loop sandbox scenario |

## CI

The sandbox-{fast,full,nightly} CI jobs run only executable scenarios:
- **fast** (PR→staging): s01, s08, s09
- **full** (rc/* promotion PR): every discovered scenario module
- **nightly** (03:00 UTC schedule): every discovered scenario module, opens hydraflow-find issue on failure
