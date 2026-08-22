# Testing


## Assert MockWorld side effects through fake adapters

MockWorld loop scenarios should use production-facing fake adapters for side
effects whenever an adapter exists. For GitHub actions, let `MockWorld` wire
`FakeGitHub` and assert on created issues, labels, comments, PRs, and CI scripts
instead of replacing `create_issue`, `post_comment`, or `add_labels` with raw
`AsyncMock` call counters. Mock only the unmodeled external boundary, such as a
`gh` subprocess, `git bisect`, or an LLM corpus runner. Cover parser and
formatter branches that sit behind those boundaries with focused unit tests.
`tests/architecture/test_mockworld_scenario_fake_boundaries.py` guards this for
MockWorld scenario files; documented Pattern B direct-instantiation tests may
still script a PRPort when the assertion is the loop's reaction to a specific
port return value.
**Why:** Adapter-backed assertions catch title/body/label drift and fake-contract
regressions that call-count-only mocks hide.


```json:entry
{"id":"01JRC_MOCKWORLD_FAKE_PORT_ASSERTIONS","title":"Assert MockWorld side effects through fake adapters","topic":"mockworld","source_type":"manual","source_issue":null,"source_repo":"T-rav/hydraflow","created_at":"2026-05-30T21:15:00+00:00","updated_at":"2026-05-30T21:15:00+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Enforce function structure limits for testability

Limit handler functions to 50 lines and registration wiring to 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Example: move callback validation from nested closures to instance methods. **Why:** Deep nesting and long functions are difficult to test in isolation and encourage tight coupling.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA0","title":"Enforce function structure limits for testability","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643489+00:00","updated_at":"2026-05-03T04:19:35.643728+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mock at definition site, not usage site

For module-level imports, patch the assignment; for deferred imports, patch the definition module. For optional dependencies, use `unittest.mock.patch.dict("sys.modules", ...)` to guarantee cleanup. Mock sub-modules explicitly (both 'sentry_sdk' and 'sentry_sdk.integrations'). **Why:** Mocking at usage site leaves stale code paths and misses circular imports.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA1","title":"Mock at definition site, not usage site","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643783+00:00","updated_at":"2026-05-03T04:19:35.643784+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mark integration tests with @pytest.mark.integration

Only mark tests that exercise real external dependencies (Docker, network, filesystem, worktrees, service instances). Tests with `spec=AsyncMock` for all deps are unit/functional. Use `pytest.mark.skipif` with `shutil.which()` for optional CLI tools. **Why:** Separates true integration tests from unit tests for faster feedback loops.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA2","title":"Mark integration tests with @pytest.mark.integration","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643796+00:00","updated_at":"2026-05-03T04:19:35.643797+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Enforce test-value standards during review

Review must request changes for skipped, xfailed, commented-out, or placeholder
tests in active coverage. Unit tests should use the documented factories and
world-building helpers instead of ad hoc setup. Integration tests should keep
real business logic wired and mock only external boundaries whose real effects
cannot run in the test environment. MockWorld scenarios should assert side
effects through fake-adapter state, not raw mock call counts. **Why:** Test
counts are meaningless when the runnable suite contains ignored tests or mocks
that decide the outcome being asserted.


```json:entry
{"id":"01JRC_TEST_VALUE_REVIEW_GATE","title":"Enforce test-value standards during review","topic":"testing","source_type":"manual","source_issue":null,"source_repo":"T-rav/hydraflow","created_at":"2026-05-31T23:45:00+00:00","updated_at":"2026-05-31T23:45:00+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Test async patterns with AsyncMock and fire-and-forget cleanup

Use `AsyncMock` with explicit `assert_called_with()`. For fire-and-forget tasks via `create_task()`, call `await asyncio.sleep(0)` before assertions. Test async context managers: idempotent close, context manager triggers close on exit, returns self. **Why:** Async fire-and-forget races without yield points; explicit sleep ensures task completion.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA3","title":"Test async patterns with AsyncMock and fire-and-forget cleanup","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643805+00:00","updated_at":"2026-05-03T04:19:35.643808+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create Python script stand-ins for subprocess/CLI testing

Instead of mocking subprocess calls, create small Python scripts acting as CLI stand-ins that log invocations to JSON-lines files for post-hoc assertions. Example: test helper script that records CLI args and exit codes to a timestamped log. **Why:** Real subprocess invocation catches shell escaping bugs and argument ordering mistakes mocks hide.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA4","title":"Create Python script stand-ins for subprocess/CLI testing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643816+00:00","updated_at":"2026-05-03T04:19:35.643817+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use conftest as single source of truth for fixture setup

Session-scoped fixtures load before test modules. Use conftest.py for sys.path manipulation and autouse fixtures for state cleanup. Reset global/module-level state in both setup and teardown. Verify cleanup with `pytest --randomly-seed` using multiple seeds. **Why:** Shared state bleeds across tests when cleanup is incomplete.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA5","title":"Use conftest as single source of truth for fixture setup","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643824+00:00","updated_at":"2026-05-03T04:19:35.643827+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Wire real business logic in integration tests, mock subprocess boundary

For integration testing with phase runners: use real StateTracker, EventBus, VerificationJudge, RetrospectiveCollector; mock only `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing. Validate state via StateTracker APIs and EventBus.get_history(). **Why:** Real phase logic catches mismatches fully-mocked runners hide.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA6","title":"Wire real business logic in integration tests, mock subprocess boundary","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643836+00:00","updated_at":"2026-05-03T04:19:35.643837+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test protocol satisfaction with structural + duck typing

Use two approaches: (1) Structural typing with `isinstance(obj, ProtocolName)` and `@runtime_checkable`; (2) Duck-typing assertions via `hasattr(obj, 'method_name')`. Use `inspect.signature()` to catch parameter drift. Parametrize tests for each protocol method. **Why:** Structural typing alone misses runtime `__getattr__` issues; duck typing alone misses signature changes.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA7","title":"Test protocol satisfaction with structural + duck typing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643856+00:00","updated_at":"2026-05-03T04:19:35.643857+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify façaded refactors with __getattr__ routing tests

When refactoring into a façade: verify `__getattr__` routes methods correctly, raises `AttributeError` for nonexistent methods, satisfies protocols via delegation, and existing tests mocking the original class still work. Sub-components receive mutable dict/set references (not copies) to shared state. **Why:** Incorrect delegation silently breaks public APIs.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA8","title":"Verify façaded refactors with __getattr__ routing tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643866+00:00","updated_at":"2026-05-03T04:19:35.643867+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test extraction by running prompt-assertion tests in isolation

When extracting prompt-building methods, run prompt-assertion tests immediately after extraction. For private method extraction with unchanged public API, existing tests provide complete coverage (no new tests needed). For parameter renames using positional arguments, refactoring is low-risk. **Why:** Post-extraction testing catches prompt generation regressions immediately.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA9","title":"Test extraction by running prompt-assertion tests in isolation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643873+00:00","updated_at":"2026-05-03T04:19:35.643875+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test Sentry/telemetry by asserting numeric values, not just key presence

Use `patch.dict("sys.modules", ...)` to mock sentry_sdk imports. Assert actual numeric values in breadcrumbs/metrics, not just presence of keys. For logging assertions, specify exact logger: `caplog.at_level(level, logger="module.name")`. Clear caplog before action. **Why:** Key-only assertions pass when values are wrong; wrong logger names miss assertions.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAA","title":"Test Sentry/telemetry by asserting numeric values, not just key presence","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643880+00:00","updated_at":"2026-05-03T04:19:35.643881+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Assert on key terms, not exact query strings

For AST-based regression tests, parse source ASTs and allow ±3 line drift. For assertions on query strings, verify specific key terms appear rather than exact string match. Use f-strings to embed constants in assertions. Use word-boundary matching to avoid collisions. **Why:** Exact query assertions break with refactoring; key-term matching is resilient.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAB","title":"Assert on key terms, not exact query strings","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643887+00:00","updated_at":"2026-05-03T04:19:35.643887+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Playwright for frontend testing, not TestClient alone

TestClient only sees initial HTML shell, not JavaScript-rendered attributes. `aria-labelledby` and client-rendered properties require Playwright or browser testing. Delete dead Python tests attempting to verify these. Organize browser test fixtures in conftest.py for reuse. **Why:** Server-side rendering misses JavaScript-dependent behavior that breaks in production.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAC","title":"Use Playwright for frontend testing, not TestClient alone","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643893+00:00","updated_at":"2026-05-03T04:19:35.643893+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never assert on absolute singleton ID values

Global singletons like `_event_counter` are shared across all instances. Tests must assert only on relative ordering and uniqueness within a single test, never on absolute values. Example: assert `id1 < id2` rather than `id1 == 42`. **Why:** Absolute ID assertions cause cross-test pollution when tests run in different orders.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAD","title":"Never assert on absolute singleton ID values","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643899+00:00","updated_at":"2026-05-03T04:19:35.643900+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Keep schema evolution tests in sync with constants

Before property-based tests, add structural tests: every target stage is valid, every stage has transition entry, no dangling references. Test constants serve as both oracles and documentation—keep synchronized. Use `len(LABELS) == 13` instead of hardcoding. **Why:** Drift between constants and tests silently allows invalid transitions.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAE","title":"Keep schema evolution tests in sync with constants","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643905+00:00","updated_at":"2026-05-03T04:19:35.643906+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Update all serialization tests when adding Pydantic fields

When adding a field to a Pydantic model (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update: `model_dump()` assertions, expected key sets in smoke tests, and any `assert result == {...}` hard-coding the full shape. **Why:** New fields silently fail in unrelated refactors when serialization tests aren't updated.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAF","title":"Update all serialization tests when adding Pydantic fields","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643911+00:00","updated_at":"2026-05-03T04:19:35.643912+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use `is None` for optional object truthiness checks

Never write `if not self._hindsight:` to test optional presence. Use explicit `if self._hindsight is None:`. Mock objects with `spec=...` and empty collections can be falsy, triggering wrong branches. Example: `if callback is None:` instead of `if not callback:`. **Why:** Identity checks are unambiguous; truthiness checks can unexpectedly match falsy objects.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAG","title":"Use `is None` for optional object truthiness checks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643917+00:00","updated_at":"2026-05-03T04:19:35.643918+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Check conftest before adding duplicate test helpers

Before adding `def _<helper>` to a test file, grep `tests/conftest.py` and `tests/helpers*.py` for similar helpers. Shared fixtures belong in conftest; duplicates cause silent drift when one copy is updated. **Why:** Duplicated helpers diverge silently when one copy gains parameters the other lacks.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAH","title":"Check conftest before adding duplicate test helpers","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643923+00:00","updated_at":"2026-05-03T04:19:35.643925+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never test ADR markdown content

Do not create `test_adr_NNNN_*.py` files asserting on markdown headings, status fields, or prose. Only test ADR-related code (e.g., `test_adr_reviewer.py` tests the reviewer logic, not the doc). **Why:** Content tests break on edits; they provide no runtime value.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAJ","title":"Never test ADR markdown content","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643930+00:00","updated_at":"2026-05-03T04:19:35.643931+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Always run make quality before declaring work complete

Run `make quality` before committing to verify lint, tests, type checks, and code coverage all pass. Do not present implementation as done until quality gates pass. **Why:** Quality gates catch regressions that individual test runs miss.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAK","title":"Always run make quality before declaring work complete","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643936+00:00","updated_at":"2026-05-03T04:19:35.643938+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Write unit tests before committing code changes

Every new function, class, or feature modification MUST include comprehensive tests in `tests/test_<module>.py` before commit. Bug fixes add regression tests in `tests/regressions/`. Coverage threshold: 70%. **Why:** Untested code causes silent regressions in background loops.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAM","title":"Write unit tests before committing code changes","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643943+00:00","updated_at":"2026-05-03T04:19:35.643943+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Kill-switch testing pattern for background loops

Every `BaseBackgroundLoop` subclass needs a unit test that asserts disabling the loop short-circuits `_do_work` to `{'status': 'disabled'}` without side effects. Construct `LoopDeps` with `enabled_cb=lambda name: name != '<worker_name>'`; mock dependent methods with `AsyncMock(side_effect=AssertionError(...))`; await `_do_work()`. **Why:** Ensures disabled loops don't execute business logic.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAN","title":"Kill-switch testing pattern for background loops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643948+00:00","updated_at":"2026-05-03T04:19:35.643949+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cassette-based fake adapter contract testing

Fake adapters in `tests/scenarios/fakes/` record cassettes against live github/git/docker/claude, normalize volatile fields (timestamps, PR numbers, SHAs), and replay via `tests/trust/contracts/_replay.py`. Cassettes are Pydantic v2 YAML for github/git/docker; .jsonl streams for claude. **Why:** Cassettes catch API contract drift that mocks miss.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAP","title":"Cassette-based fake adapter contract testing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643954+00:00","updated_at":"2026-05-03T04:19:35.643955+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Meta-observability with bounded recursion via trust fleet

TrustFleetSanityLoop monitors 9 trust loops for anomalies: issues_per_hour, repair_ratio, tick_error_ratio, staleness, cost_spike. HealthMonitorLoop is the dead-man-switch watching TrustFleetSanityLoop. Recursion is bounded because trust-loop set is frozen and HealthMonitorLoop is outside the trust-fleet floor. **Why:** Unbounded recursion breaks observability.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAQ","title":"Meta-observability with bounded recursion via trust fleet","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643960+00:00","updated_at":"2026-05-03T04:19:35.643961+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## MockWorld fixture composes all external fakes into controllable environment

Wire FakeGitHub, FakeLLM, FakeHindsight, FakeWorkspace, FakeSentry, FakeClock as stateful in-memory fakes (not AsyncMock). Expose fluent API: `world.add_issue()`, `world.set_phase_result()`, `world.fail_service()`, `await world.run_pipeline()`. Assertions inspect final state directly. **Why:** Stateful fakes catch behavioral bugs AsyncMock misses.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAR","title":"MockWorld fixture composes all external fakes into controllable environment","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643970+00:00","updated_at":"2026-05-03T04:19:35.643971+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Scenario tests are additive to unit and integration tests

Unit tests (9K+) test individual functions. Integration tests (`PipelineHarness`) test phase wiring with mocked runners. Scenario tests test complete flows with stateful fakes. All three tiers coexist; scenario tests don't replace the others. **Why:** Each tier catches different bug classes.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAS","title":"Scenario tests are additive to unit and integration tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643976+00:00","updated_at":"2026-05-03T04:19:35.643977+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run scenario tests with make scenario and make scenario-loops

Execute `make scenario` for pipeline scenarios (`pytest -m scenario`) and `make scenario-loops` for background loop scenarios (`pytest -m scenario_loops`). Both are included in `make quality`. **Why:** CI needs explicit markers to run scenario tests in gates.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAT","title":"Run scenario tests with make scenario and make scenario-loops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643981+00:00","updated_at":"2026-05-03T04:19:35.643982+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Caretaker-loop Pattern A: catalog-driven invocation

Use `await world.run_with_loops(["loop_name"], cycles=1)` when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate; works with default catalog config. **Why:** Avoids manual loop instantiation and dependency wiring.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAV","title":"Caretaker-loop Pattern A: catalog-driven invocation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643987+00:00","updated_at":"2026-05-03T04:19:35.643988+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Caretaker-loop Pattern B: direct instantiation with config overrides

Use `_make_loop_deps(world, config_overrides={...})` and construct the loop class directly when: config flags differ from catalog defaults, or loop is not yet registered. See: `tests/helpers.py:_make_loop_deps`. **Why:** Enables testing with custom config without modifying the catalog.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAW","title":"Caretaker-loop Pattern B: direct instantiation with config overrides","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643994+00:00","updated_at":"2026-05-03T04:19:35.643995+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test concurrent file operations with deterministic iteration counts

Test concurrent file operations using `concurrent.futures.ThreadPoolExecutor` with fixed thread counts and deterministic iterations (e.g., 10 threads × 20 events = 200 total). Assert exact event counts. POSIX guarantees atomicity for writes under ~4KB, so concurrent appends should be safe—validate empirically. **Why:** Timing-based assertions are flaky; iteration counts are deterministic.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAX","title":"Test concurrent file operations with deterministic iteration counts","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644000+00:00","updated_at":"2026-05-03T04:19:35.644001+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory bank deduplication uses priority mapping

Priority: LEARNINGS=5, TROUBLESHOOTING=4, RETROSPECTIVES=3, REVIEW_INSIGHTS=2, HARNESS_INSIGHTS=1. When duplicates collide, higher-priority item survives. Bank keys must be consistent across dedup and assembly pipelines. Fallback recall tries multiple field names: `learning`, `text`, `content`, `display_text`, `description`. **Why:** Inconsistent keys silently miss banks during dedup.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54A","title":"Memory bank deduplication uses priority mapping","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644008+00:00","updated_at":"2026-05-03T04:19:35.644010+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Skill definition replication requires 4 backend consistency

HydraFlow skills replicate across 4 backends: .claude/commands/, .pi/skills/, .codex/skills/, src/*.py. Use manual SKILL_MARKERS mapping to validate all copies contain matching output markers. Consistency tests check marker presence via substring search. Each skill change requires updating all 4 copies. **Why:** Divergent copies cause silent skill failures in some execution contexts.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54B","title":"Skill definition replication requires 4 backend consistency","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644016+00:00","updated_at":"2026-05-03T04:19:35.644016+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cross-location key consistency is critical for data pipelines

Memory deduplication and skill replication depend on consistent naming across locations. If location names or field names differ, data is silently missed. Verify bank_order keys match dict keys and skill markers match across 4 backends with identical text. **Why:** Silent misses during validation or deduplication break trust in the system.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54C","title":"Cross-location key consistency is critical for data pipelines","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644023+00:00","updated_at":"2026-05-03T04:19:35.644024+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Feature toggle implementation requires config field + ENV override

Feature toggles need both: (1) config field definition in `src/config.py`, (2) `_ENV_INT_OVERRIDES` entry for env-var override. Both are necessary for runtime configurability. Test both default value and environment-variable override behavior. **Why:** Incomplete toggles cannot be controlled at runtime.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54D","title":"Feature toggle implementation requires config field + ENV override","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644031+00:00","updated_at":"2026-05-03T04:19:35.644032+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test pyramid — three layers, all required for load-bearing features

Every load-bearing feature ships through unit + MockWorld scenario + sandbox e2e tests before merging to staging. Skipping a layer is a procedural failure, not a judgment call. Unit tests catch code-path bugs but are blind to real-API behavior; MockWorld scenarios catch loop-integration bugs unit tests can't see; sandbox e2e tests catch the docker / wiring / UI layer that MockWorld can't reach. See [`docs/standards/testing/README.md`](../standards/testing/README.md) for the canonical reference: when each layer is required, how to write each (Pattern A full-MockWorld vs Pattern B direct-instantiation), and the anti-patterns (asserting against non-existent state shapes; module-level `import pytest` in sandbox scenarios; "this feature is too small for scenario tests" rationalisation).

**Why:** PR #8482 (rebase-on-conflict) shipped with only unit tests and was caught by the question "did you test it all?". The MockWorld and sandbox layers were added in a follow-up. The standard exists so this doesn't recur.


```json:entry
{"id":"01KQTESTPYRAMID2026B0PHASE3","title":"Test pyramid — three layers, all required for load-bearing features","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-07T05:30:00.000000+00:00","updated_at":"2026-05-07T05:30:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## Deterministic coverage-delta cross-check — execution ≠ assertion

The `test-adequacy` skill in the implementer loop runs a deterministic cross-check after the LLM verdict: `make coverage 0` collects a Cobertura XML report and any changed production line that appears in no test's execution trace forces the skill result to RETRY, overriding an LLM PASS. The check runs **once per skill invocation**, after the LLM attempt loop, not on each retry.

The asymmetry is load-bearing: coverage proves *execution*, not *assertion*. A line executed at import time with zero assertions shows as covered. Therefore a deterministic GAPS signal → hard RETRY, but a deterministic CLEAN signal does **not** suppress an LLM RETRY — the model may still flag weak or missing assertions that execution traces cannot detect.

The check is fail-open: when `make coverage 0` fails, times out, or produces no `coverage.xml`, the LLM verdict is preserved unchanged. New files absent from the coverage report are skipped (no data = no assertion). The timeout is configured via `HYDRAFLOW_TEST_ADEQUACY_COVERAGE_TIMEOUT_SECS` (default 300 s, minimum 60 s); set `max_test_adequacy_attempts=0` to disable the skill entirely.

The interactive `hf.test-adequacy` slash command remains read-only and LLM-only — the coverage subprocess runs only inside the implementer loop.

**Why:** LLM-only test-adequacy verdicts can self-rubber-stamp: the same model that generated the implementation judges whether it is adequately tested. The deterministic check adds a signal that cannot be influenced by the model's confidence in its own output.


```json:entry
{"id":"01KRCOVDELTA2026TESTADEQUACY","title":"Deterministic coverage-delta cross-check — execution != assertion","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-06-20T00:00:00.000000+00:00","updated_at":"2026-06-20T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## Regression-rot detector — hosted in StaleIssueLoop, not a new loop (#9597)

`StaleIssueLoop`'s existing daily tick also scans `tests/regressions/{test,regression}_issue_<N>*.py` for the RED `xfail(reason="... fix not yet landed", strict=False)` marker (parsed statically from file text — no pytest invocation) and classifies two rot patterns: **false-close rot** (issue closed, pin still RED — fires immediately regardless of age) and **orphaned-RED** (issue open, pin RED for more than `stale_issue_regression_rot_stale_days` days, default 14). Age is tracked via a small persisted first-seen timestamp store (`RegressionRotTimestamps`) rather than `git log` — CI/sandbox checkouts are frequently shallow, which would make a file's first-commit date look artificially recent or unavailable.

Findings surface as **one** rolling issue via `RollupIssueManager` (body refreshed per tick, auto-closed once every finding clears) — not one issue per finding. An explicit `# hydraflow-regression-rot: blocked-on #<N>` annotation anywhere in the file exempts it from both classifications (the "legitimately held back pending another issue" case, e.g. #9415 blocked on #9080).

Surface 2 covers the working tree: `.githooks/pre-push` runs `scripts/check_regression_rot_working_tree.py`, an offline (`git status --porcelain` only — no `gh` calls) advisory that warns, but never blocks, on uncommitted `tests/regressions/*_issue_<N>*.py` files. This closes the gap behind the 2026-06-13 incident, where 12 RED regression tests sat uncommitted in a dev checkout with their issues still open and nothing warned before the work was pushed/lost.

**Why:** No new caretaker loop. `StaleIssueLoop` already runs a daily, full-repo, issue-state-aware sweep — the same cadence and issue-filing shape the detector needs — so hosting the check there avoids duplicating the six-site wiring (config knob, service_registry, orchestrator, dashboard, MockWorld catalog builder, kill-switch/fitness overrides) a dedicated loop would require.


```json:entry
{"id":"01KRREGRESSIONROT9597HOSTED","title":"Regression-rot detector — hosted in StaleIssueLoop, not a new loop (#9597)","topic":null,"source_type":"compiled","source_issue":9597,"source_repo":null,"created_at":"2026-07-19T00:00:00.000000+00:00","updated_at":"2026-07-19T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## Cancelled-at-timeout: continuous progress means capacity, not a hang (#10883)

A CI job CANCELLED by GitHub's own `timeout-minutes` enforcement, with a test step that never reached a terminal conclusion, looks identical whether the run was genuinely wedged (a real `os.killpg` reaching the CI container's own PID 1 via a mocked subprocess `.pid` — the #9983/#10002 class) or simply outgrew its time budget. The discriminator is **progress shape**, not the cancellation itself: pull the job log and check whether pytest's progress dots advanced continuously up to the moment of cancellation (capacity — the lane is just too slow for its budget) versus stalling with no output for an extended stretch before the kill (a genuine wedge). `Coverage (trailing)` hit the capacity case: single-threaded (`-p no:xdist`), 23,011 tests, steady progress to 81% at cancellation, zero terminal stall — the fix was parallelizing the lane under xdist plus `--timeout` per test, not another killpg hunt (PR #10410 had already hardened `is_real_pid` for the prior incident and the cancellations continued unchanged).

`GateHealthLoop.find_suspected_hangs` encodes this distinction structurally: a check hitting the cancelled-at-timeout signature once in the analyzed window files a `suspected_hang` (the killpg/mocked-`.pid` playbook, worth chasing for a single incident); the same check hitting it two-plus times in one window collapses to a single `chronic_timeout` finding instead (fingerprinted on check name alone, no run id, so it dedupes across cycles) — a repeated pattern is a capacity problem worth parallelizing/sharding/re-budgeting, and pointing it at the killpg playbook would misdirect every time.

**Why:** Before #10883, every cancelled-at-timeout run filed a fresh `suspected_hang` issue (fingerprint included run_id), so one chronically over-budget lane fanned out into one killpg-hunt issue per push (#10390, #10391, #10393, #10883) — always the wrong diagnosis for a lane that just needs to run faster.

_Source: #10883 (plan)_


```json:entry
{"id":"01KRCHRONICTIMEOUT10883HANG","title":"Cancelled-at-timeout: continuous progress means capacity, not a hang (#10883)","topic":null,"source_type":"plan","source_issue":10883,"source_repo":null,"created_at":"2026-07-31T00:00:00.000000+00:00","updated_at":"2026-07-31T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## Light lane sandbox air-gap — AutoAgentPreflightLoop spawns through the seed-scripted fake

With the #11298 auto-agent light lane ON by default (#11590), any sandbox scenario whose issue is triage-scored at complexity ≤ `auto_agent_light_max_complexity` routes to `AutoAgentPreflightLoop` instead of the staged plan pipeline. The loop's `_build_spawn_fn` constructs its `AutoAgentRunner` inside the method — not injected — so none of the existing air-gaps (the `subprocess_runner=` injection, the `_mockworld_fake_llm` sentinels) could reach it. `mockworld.sandbox_main.air_gap_runner_sentinels` now rebinds `_build_spawn_fn` to `build_seeded_auto_agent_spawn_builder`: the spawn pops `seed.scripts["auto_agent"]` entries via `FakeLLM.next_auto_agent_spawn` (a `resolved` entry mints the PR through the PRPort on the auto-agent branch so review discovers it like a real one); an UNSCRIPTED issue gets a deterministic crashed spawn, logged — never a real subprocess. The same builder is wired in `MockWorld.run_with_loops` (the `auto_agent_spawn_builder` port), so both tiers share one seam. Prerequisite for any in-container auto-agent behavior at all: `Dockerfile.agent` ships `prompts/` into `/opt/hydraflow` — before #11590 the image had no playbooks and every in-container spawn died on `FileNotFoundError` before it could even fail auth.

**Why:** the first lane-on runs of s54/s55 wedged on `Agent CLI authentication failed` retries — the decomposed children routed to the lane and spawned a real `claude` inside the air-gapped container; the seam-completeness ratchet never flagged it because the loop module has no lexical spawn call (the spawn lives in the runner it constructs). Scenario recipe: script `{"status": "resolved"}` per light-lane issue (s92, s54, s55), or a failure shape (`needs_human`/`crashed`) to drive the unhappy path.

_Source: #11590 (build)_


```json:entry
{"id":"01M0K5AREKCQMM12BWRNEC6KJW","title":"Light lane sandbox air-gap — AutoAgentPreflightLoop spawns through the seed-scripted fake","topic":null,"source_type":"manual","source_issue":11590,"source_repo":null,"created_at":"2026-08-21T22:30:00.000000+00:00","updated_at":"2026-08-21T22:30:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## A `BaseSubprocessRunner` construction is a spawn site the seam scan cannot see (#11602)

The sandbox seam-completeness ratchet (`tests/architecture/test_sandbox_seam_completeness.py`) AST-scans loop/runner modules for **spawn primitives** (`stream_claude_process`, `run_subprocess*`, …). A `BaseSubprocessRunner` subclass has none: it spawns through the base's `run`, so the module that CONSTRUCTS one — `service_registry.build_services`, a loop's `_get_runner`, a phase — produces no spawn signature and the ratchet stays green while the instance can shell out to a real `claude` inside the air-gapped container. #11590 (`AutoAgentPreflightLoop._build_spawn_fn`) and #11602 (three composition-root `AutoAgentRunner`s) are the two recurrences.

`scan_runner_constructions` closes it by enumerating the construction sites themselves; each must declare its seam in `RUNNER_CONSTRUCTION_SEAMS`. **Which seam is available depends on where the runner is built:**

- **Injected at the composition root** (built once, handed to a loop) → `mockworld_sentinel`. The instance outlives construction, so `air_gap_runner_sentinels` attaches `_mockworld_fake_llm` (add the loop to `_SENTINEL_RUNNER_LOOPS`) and `BaseSubprocessRunner.run` consults it before the spawn, returning a deterministic CRASHED outcome.
- **Built inside a method, per call** → no sentinel can ever be attached, because the object does not exist until spawn time. The site needs a `config_disable` on its loop or a `seed_seam` that replaces the enclosing builder wholesale.

**Why:** the consult lives on `BaseSubprocessRunner.run` rather than on each subclass precisely because per-subclass consults are what let these sites slip — one seam on the base covers every subclass at once, and `SANDBOX_SEAMS["base_subprocess_runner"] = "mockworld_sentinel"` finally means what it says (before #11602 neither subclass consulted anything, so that declaration covered nothing).

_Source: #11602 (implement)_


```json:entry
{"id":"01KRSUBPROCRUNNERCONSTRUCT11602","title":"A BaseSubprocessRunner construction is a spawn site the seam scan cannot see (#11602)","topic":null,"source_type":"implement","source_issue":11602,"source_repo":null,"created_at":"2026-08-22T00:00:00.000000+00:00","updated_at":"2026-08-22T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```

## Sandbox verification runs belong in CI, not on the factory host (#11601)

Local `docker compose -f docker-compose.sandbox.yml` runs are for **developing** a scenario: the fast edit/run loop, `python scripts/sandbox_scenario.py shell`, poking the stack by hand while the assertions are still being written. They are **not** how a scenario gets verified. The factory host is one Mac driving the whole pipeline toward 20+ merged PRs/day; a compose stack booted on it during production hours competes for the exact CPU/RAM/docker daemon the factory needs, and sandbox e2e was the last heavy workload still tied to that host.

Verification runs go to a GitHub runner via the **Sandbox Scenario (dispatch)** workflow (`.github/workflows/sandbox-dispatch.yml`): `workflow_dispatch` with a `ref` (default the default branch) and a `scenario` (a scenario name, `fast` for the PR→staging subset, or `all`). It runs `scripts/sandbox_scenario.py run <name>` on the runner and prints the PASS/FAIL verdict plus an 80-line log tail into `$GITHUB_STEP_SUMMARY`, so the operator reads the answer without opening the log or the host. `gh workflow run "Sandbox Scenario (dispatch)" -f ref=<branch> -f scenario=<name>`. It is a manual lane only — never a required check, never attached to a PR.

What made that affordable is the layer cache. Every sandbox lane used to run `docker compose build … hydraflow …`, rebuilding the ~3 GB `Dockerfile.agent` image from scratch: ~10 min per lane, and the entire exposure surface for the recurring NodeSource CDN 403 flake (the apt/NodeSource/uv layers are re-fetched on every single run). The lanes now call the `.github/actions/build-agent-image` composite action, which builds with buildx against a GHCR registry cache (`ghcr.io/<owner>/hydraflow-agent:sandbox-buildcache`, `mode=max` — required, because the expensive layers live in `base`/`tools` stages the runtime stage only `COPY --from`s) and loads the result as `hydraflow-agent-sandbox:local`, the tag `docker-compose.sandbox.yml` now pins for the `hydraflow` service.

Two couplings make that actually save time rather than merely look cached. First, compose only builds a service whose image is absent, so the pre-loaded tag short-circuits it — but the workflow's own `docker compose build` list must then **omit** `hydraflow`. Second, `scripts/sandbox_scenario.py` rebuilds every service before each scenario, and the runner daemon's builder does **not** share buildx's cache; the composite action therefore exports `SANDBOX_BUILD_SERVICES` so the harness skips the service it already built. Forget either and the cache is silently thrown away with no red anywhere.

Only trusted push/schedule lanes write the cache (`push-cache: 'true'` + `packages: write` on the post-merge-smoke and nightly jobs); every `pull_request` lane reads it with `packages: read`. A mutable cache ref a PR could overwrite is a cache-poisoning sink in a public repo, and the cache-writing context must only ever see already-merged code.

**Why:** at 20+ PRs/day the host is the constraint, and "verify it locally" quietly spends the constraint. Moving verification to CI only helps if CI is fast: 10 min × every sandbox lane × every PR was the reason people ran it locally in the first place. The 2 GB agent-image size gate stays exactly where it was (`build-agent-image.yml`, rc/* → main) — caching changes how the image is built, never what ships in it.

_Source: #11601 (plan)_


```json:entry
{"id":"01KSANDBOXCIDISPATCH11601WIKI","title":"Sandbox verification runs belong in CI, not on the factory host (#11601)","topic":null,"source_type":"plan","source_issue":11601,"source_repo":null,"created_at":"2026-08-22T00:00:00.000000+00:00","updated_at":"2026-08-22T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
