# ADR-0023: Tests Must Match Toggle State They Assert

**Status:** Proposed
**Date:** 2026-03-08

## Context

HydraFlow uses boolean config toggles (fields on `HydraFlowConfig` in `src/config.py`)
to gate code paths at runtime. For example, `visual_gate_enabled` controls whether
the review phase runs visual validation via `ReviewPhase.check_visual_gate` or skips
it entirely. The toggle check happens at the call site, and the gated method is only
invoked when the toggle is in the correct state.

A recurring test bug pattern has been identified: tests patch the inner method (e.g.,
`check_visual_gate`) and assert it was called, but never enable the config toggle that
gates its call site. Because the toggle defaults to `False`, the patched method is
never reached, and the test either silently passes (if it asserts `called` without
checking call count) or gives a false-negative that masks real regressions.

**Anti-pattern** (toggle not set — assertion passes vacuously):

```python
async def test_visual_gate_called(review_phase):
    with patch.object(review_phase, "check_visual_gate") as mock_gate:
        await review_phase.finalize_merge(pr)
        mock_gate.assert_called_once()  # never reached — toggle is False
```

**Correct** (toggle explicitly enabled):

```python
async def test_visual_gate_called(review_phase):
    review_phase._config.visual_gate_enabled = True
    with patch.object(review_phase, "check_visual_gate") as mock_gate:
        await review_phase.finalize_merge(pr)
        mock_gate.assert_called_once()  # gate is enabled, method is reached
```

This pattern was first discovered during review of toggle-gated routing in the review
phase (see memory issue #2350) and confirmed by a related finding (issue #2346). While
the original motivating toggle (`adr_auto_triage`) has since been removed as part of a
feature-flag cleanup, the underlying discipline remains relevant — any boolean config
field that gates a code path is susceptible to the same class of silent test bug.

The root cause is that test fixtures and config construction are decoupled from the
assertions they support. Nothing in the test infrastructure enforces that a fixture
enabling a particular code path also sets the toggle that guards it.

## Decision

Adopt the following rules for all tests that exercise config-toggle-gated code paths
in HydraFlow:

### 1. Toggle-assertion consistency

Every test that asserts a toggle-gated code path is executed **must** explicitly set
the corresponding config toggle to the state that enables that path. The toggle must
be set on the `HydraFlowConfig` instance used by the system under test — not on a
separate config object or only in a mock.

### 2. Negative-path coverage

For each toggle-gated branch, there **should** be a companion test that sets the
toggle to the opposite state and asserts the gated path is **not** taken (e.g., the
alternative path or early return is exercised instead).

### 3. Review checklist item

During code review of any PR that touches toggle-gated logic, reviewers must verify:

- Test fixtures set config toggles consistently with the assertions they make.
- Patched inner methods are reachable given the toggle state in the fixture.
- Both the enabled and disabled toggle states have test coverage.

### 4. Scope boundaries

This decision applies to all boolean (and enum-valued) config fields on
`HydraFlowConfig` that gate code paths via conditional checks. It does not prescribe
a specific testing framework or fixture pattern — teams may use `@pytest.fixture`,
inline config construction, or parametrized tests as long as the toggle-assertion
consistency rule is satisfied.

### Operational impact on HydraFlow workers

- No runtime changes to workers. This ADR governs test discipline only.
- Workers continue to read toggles from `HydraFlowConfig` at startup; the decision
  ensures that the test suite faithfully mirrors those runtime conditions so
  regressions in toggle-gated routing are caught before merge.

## Consequences

**Positive**

- Eliminates a class of silent test bugs where assertions pass vacuously because the
  gated code path was never reached.
- Makes toggle-dependent behaviour explicit in test code, improving readability and
  reducing the debugging cost when a toggle-gated feature regresses.
- The review checklist item catches future instances of the pattern during PR review,
  preventing recurrence.

**Negative / Trade-offs**

- Slightly increases test verbosity: each toggle-gated path needs its toggle set
  explicitly, even when the default happens to match. Explicit is preferred over
  implicit to avoid breakage if defaults change.
- Companion negative-path tests add to the test count, increasing CI time marginally.
- Reviewers must understand which config fields gate which code paths, raising the
  knowledge bar for new contributors reviewing toggle-heavy modules.

## Alternatives considered

1. **Rely on integration tests only** — rejected because integration tests are slower
   and the toggle-consistency bug is a unit-level concern that should be caught early.
2. **Automated lint rule or test-config defaults** — a static-analysis rule to detect
   unset toggles was considered but deferred because introspecting mock/fixture setups
   is fragile. Changing toggle defaults to `True` in test configs was also rejected
   because it would invert the same class of bug: tests would miss the disabled
   fallback path instead of the enabled path.

## Related

- Source memory: [#2350 — Tests must match toggle state they assert](https://github.com/T-rav/hydra/issues/2350)
- Implementing issue: [#2356](https://github.com/T-rav/hydra/issues/2356)
- Related learning: [#2346 — Toggle must gate the triage call, not just the HITL fallback](https://github.com/T-rav/hydra/issues/2346)
