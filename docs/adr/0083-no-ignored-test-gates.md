# ADR-0083: No ignored automated test gates

- **Status:** Accepted
- **Date:** 2026-05-30
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0052](0052-sandbox-tier-scenarios.md)
- **Enforced by:** `tests/test_sandbox_scenario_contract.py`, `tests/test_no_screenshot_regression_tests.py`

## Context

HydraFlow's testing standard depends on three layers: unit, MockWorld scenario,
and sandbox e2e. A skipped, xfailed, placeholder, or screenshot-baseline test
looks like coverage in inventory but does not protect the factory. It lets the
catalog claim a behavior is gated while CI cannot actually reject a regression.

The sandbox tier is especially sensitive because it is the dark-factory merge
gate for Docker, dashboard, orchestration, and Fake adapter wiring. A scenario
that prints a tracking issue and exits successfully is an ignored test, even if
it does not use `pytest.skip`.

## Decision

Automated test gates must be executable contracts. A test that cannot assert a
real behavior is removed from the runnable suite until the missing harness or
product behavior exists.

Rules:

1. No new `pytest.skip`, `pytest.xfail`, placeholder pass, or soft-pass behavior
   in sandbox scenarios.
2. Sandbox scenarios must assert API, DOM, event, state, or user-observable
   behavior. Printing a warning and returning success is not a test.
3. Screenshot or pixel-baseline comparisons are not trusted quality oracles.
   UI coverage uses semantic DOM, accessibility role, API/state, event, and
   sandbox assertions.
4. Missing coverage is tracked as work in `bd`; it is not represented as a
   green placeholder test.

## Consequences

Positive:

- The sandbox catalog reflects real merge gates only.
- Coverage audits stop counting ignored tests as protection.
- CI failures point at executable contracts rather than stale placeholder text.

Negative:

- Removing non-working scenarios reduces the visible scenario count until the
  missing harness behavior is implemented.
- Some previously documented coverage claims must be downgraded to known gaps.

## Source-file citations

- `tests/test_sandbox_scenario_contract.py` — static contract for runnable
  sandbox scenarios.
- `tests/test_no_screenshot_regression_tests.py` — guard against screenshot
  regression-test hooks and tracked screenshot snapshot directories.
- `docs/standards/testing/README.md` — canonical three-layer test standard.
