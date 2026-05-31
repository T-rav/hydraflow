# HydraFlow Standard — Test Pyramid

Every load-bearing feature in HydraFlow ships through three layers of tests
before it merges into the integration branch. Skipping a layer is a
procedural failure — not a judgment call. Unit tests catch code-path bugs
but are blind to real-API behavior; MockWorld scenarios catch integration
bugs unit tests can't see; sandbox e2e tests catch the docker / wiring / UI
layer that MockWorld can't reach. Skipping layers ships features that pass
in isolation but break under real conditions.

## The three layers

```
                    ┌────────────────────────┐
                    │  Sandbox e2e (~minutes) │   tests/sandbox_scenarios/
                    │  docker-compose +      │   sNN_*.py + Playwright
                    │  Playwright            │
                    └────────┬───────────────┘
                             │
                  ┌──────────┴──────────────┐
                  │  MockWorld scenario     │   tests/scenarios/
                  │  (~seconds)             │   test_*_scenario.py
                  │  real loops + Fake*     │   uses MockWorld + FakeGitHub
                  │  adapters at boundary   │
                  └──────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │  Unit (~milliseconds)        │  tests/test_*.py
              │  pure functions, mocks at   │  AsyncMock collaborators,
              │  every collaborator         │  monkeypatch run_subprocess
              └─────────────────────────────┘
```

| Layer | Where | What it proves | Mocks at |
|---|---|---|---|
| **Unit** | `tests/test_*.py` | Code paths and edge cases of one function/class | All collaborators |
| **MockWorld scenario** | `tests/scenarios/test_*_scenario.py` (mark `pytest.mark.scenario_loops`) | Real loop / runner code interacts with `MockWorld`'s `Fake*` adapters at the I/O boundary. Catches integration bugs unit tests can't see. | Subprocess / network boundary only |
| **Sandbox e2e** | `tests/sandbox_scenarios/scenarios/sNN_*.py` + `tests/sandbox_scenarios/runner/` | The real orchestrator boots inside `docker-compose.sandbox.yml`, Playwright drives the UI, the dashboard API verifies state. The dark-factory production bar. | Only at the docker-compose seam (FakeLLM, FakeGitHub via the sandbox entrypoint) |

## When each layer is required

A feature merges into `staging` when ALL three layers exist for it. Specifically:

| Feature shape | Unit | Scenario | Sandbox |
|---|---|---|---|
| New port method (e.g. `update_pr_branch`) | ✅ required | ✅ required (via the loop that calls it, using a real PRManager + FakeGitHub at the boundary) | ✅ required (drive the loop end-to-end in docker) |
| New loop or runner | ✅ required | ✅ required (Pattern B direct instantiation OR full MockWorld flow) | ✅ required (sNN scenario) |
| New phase decoration / cross-cutting concern (OTel, telemetry) | ✅ required | ✅ required (assert against `world.honeycomb` / equivalent fake) | ⚠️ recommended (skip only if the cross-cut has no observable runtime effect) |
| Pure refactor with no behavior change | ✅ required | (existing scenario coverage stays green) | (no new sandbox needed) |
| Bug fix | ✅ required (regression test in `tests/regressions/`) | ✅ required if the bug is observable through a loop / runner path | ⚠️ if the bug only manifests under sandbox conditions |
| New ADR / wiki / config | ❌ no test (docs) | ❌ | ❌ |

## How to write each layer

### Unit tests
- Live in `tests/test_<module>.py`
- One assertion per test; AAA structure (Arrange / Act / Assert) but **no AAA comments** (the test-sludge guard rejects them — see `docs/wiki/testing.md`)
- Mock every collaborator: AsyncMock for async, monkeypatch for `run_subprocess` / module-level state
- Use `tests.helpers.ConfigFactory.create()` for `HydraFlowConfig`
- Use `tests.helpers.make_pr_manager(config=, event_bus=)` for a real `PRManager` with mocked I/O

### MockWorld scenario tests
- Live in `tests/scenarios/test_<feature>_scenario.py`
- Mark with `pytestmark = pytest.mark.scenario_loops`
- **Two patterns:**
  - **Pattern A (full MockWorld):** import `MockWorld`, set up via builder methods (`add_repo`, `add_issue`, `set_phase_result`, `fail_service`), drive a phase or loop tick, assert against `world.<fake>`. Use this when the test exercises orchestration + multiple ports.
  - **Pattern B (direct instantiation):** build the loop directly with `LoopDeps` + a `MagicMock(spec=PRPort)` whose methods are scripted. Use this when the test exercises a single loop's reaction to specific port outcomes (e.g. `prs.merge_promotion_pr` returns False → loop files find-issue). Existing example: `tests/scenarios/test_caretaker_loops_part2.py::TestL22StagingPromotionLoop`.
- The choice is governed by what's being asserted. Pattern A asserts cross-cutting outcomes ("after the phase ran, the dashboard reflects X"). Pattern B asserts a loop's reaction surface ("when the port returns Y, the loop does Z").
- **Do not replace FakeGitHub side effects with raw mocks in MockWorld scenarios.** If a Pattern A test expects `create_issue`, `post_comment`, `add_labels`, `close_issue`, or related PR/issue mutations, let `MockWorld` wire `FakeGitHub` and assert `world.github.issue(...)`, labels, comments, PR records, or issue state. Keep raw `AsyncMock`/`MagicMock` PR ports only in documented Pattern B direct-instantiation tests or for boundaries FakeGitHub cannot model yet. `tests/architecture/test_mockworld_scenario_fake_boundaries.py` enforces this.

### Sandbox e2e scenarios
- Live in `tests/sandbox_scenarios/scenarios/sNN_<feature>.py`
- Each scenario file exports `NAME`, `DESCRIPTION`, `seed() -> MockWorldSeed`, `async def assert_outcome(api, page) -> None`
- Run via `python scripts/sandbox_scenario.py run <NAME>` inside the docker stack (CI path: `Sandbox (PR→staging fast subset)` / `Sandbox (rc/* promotion PR full suite)` / `Sandbox (nightly regression)`)
- The `assert_outcome` body uses the dashboard API (`api.get("/api/state")`) and Playwright (`page.click(...)`) to verify production-shaped behavior
- **Scenarios must not call `pytest.skip` or `pytest.xfail`.** A sandbox scenario
  either asserts a real runtime contract or it is removed from the runnable
  catalog until the harness can support it.
- **Do not use screenshot or pixel-baseline assertions as automated quality
  gates.** Browser and sandbox coverage should assert semantic DOM state,
  accessibility roles, dashboard API state, emitted events, and user-observable
  behavior. Operator bug-report screenshots are product data, not test oracles.

## Fake adapters, cassettes & the coverage matrix (ADR-0047)

These conventions govern fakes, contract cassettes, and any tooling that
audits or generates the coverage matrix. They were corrected during the
coverage-matrix-baseline work (PR #8738) after the original spec — which is
gitignored and does not survive session boundaries — got several details
wrong. Canonicalised here so the generator slice and future audits agree.

- **Fakes live in `src/mockworld/fakes/`**, not `tests/scenarios/fakes/`.
  Per [ADR-0047](../../adr/0047-fake-adapter-contract-testing-cassettes.md)
  and codebase inspection, the Fake adapter implementations are production
  test-support code under `src/mockworld/fakes/` (e.g. `fake_github.py`,
  `fake_docker.py`). Any "Fake adapter" column in the coverage matrix must
  point there.
- **Fake naming strips the `Port` suffix: `Fake<base>`, not `Fake<PortName>`.**
  A `WorkspacePort` is implemented by `FakeWorkspace`, a `PRPort` by
  `FakeGitHub` (the concrete-adapter base name), never `FakeWorkspacePort`.
- **Cassette and Contract columns are per *adapter*, not per *port*.**
  ADR-0047 trust contracts are recorded per concrete adapter — `github` /
  `git` / `docker` / `llm` — not per port interface. In the coverage matrix
  the Ports section marks both the Cassette and Contract columns **N/A**;
  those columns belong only to the per-adapter section. A generator that
  emits per-port cassette/contract cells is wrong.
- **Bead filing uses `bd create --silent`, not `bd q --description`.**
  `bd q --description "..."` does not exist. The working command is
  `bd create --silent --title "..." --description "..."`. Bead IDs are short
  alphanumeric strings (e.g. `advisor-bpl`), not sequential integers — any
  tooling that parses or generates bead IDs must not assume numeric IDs.

## Anti-patterns

- **"My feature is too small to need scenario / sandbox tests."** This is the rationalisation that ships features which pass unit tests but break in real conditions. If the feature has any observable runtime path through a loop or the orchestrator, both higher layers apply. Real-API behavior (e.g. GitHub's update-branch endpoint, OAuth flows, third-party rate limits) is invisible to unit tests.

- **Asserting against state shapes that don't exist.** Scenarios authored against fields that aren't in `StateData` will pass at write-time (Python dicts are tolerant) but fail in CI when the missing key raises `KeyError`. Always `grep` the source-of-truth model file for the field name before asserting on it.

- **Importing pytest or skipping at runtime in sandbox scenarios.** The sandbox
  runner doesn't have pytest available for scenario modules as a product
  dependency, and skip/xfail hides a broken contract. Remove the scenario from
  the runnable catalog until it can assert real behavior.

- **Placeholder sandbox scenarios.** Printing "tracking issue" and returning
  success is an ignored test by another name. File the follow-up in `bd`; do not
  keep a green scenario file without a load-bearing assertion.

- **Scenario tests that just unit-test through a fake.** Pattern B is fine when the loop's reaction surface is what matters — but if the test could equivalently be written as a unit test of one method, it's not really a scenario test.

- **MockWorld scenarios that assert GitHub call counts instead of fake state.**
  `create_issue.assert_awaited_once()` proves the call happened, not that
  HydraFlow filed the right issue, labels, body, or state transition. Assert
  the `FakeGitHub` state unless the test is explicitly documented as Pattern B.

- **Screenshot or pixel-baseline regression tests.** They are noisy and
  low-signal for HydraFlow's UI. Prefer role/text/state/API assertions that
  explain the broken contract directly.

## Discoverability

This standard lives at three load-bearing surfaces in any HydraFlow-format repo:

- This document — the canonical reference
- [`docs/wiki/testing.md`](../../wiki/testing.md) — operator wiki entry pointing here
- `CLAUDE.md` Quick Rules — one-line directive that all features ship with the full pyramid

Drift detection: a future audit (extension of `principles_audit_loop`) should check that every PR landing on the integration branch adds at least one test in `tests/test_*.py`, one in `tests/scenarios/test_*.py`, and one in `tests/sandbox_scenarios/scenarios/sNN_*.py` — exempting docs-only and pure-refactor PRs.
