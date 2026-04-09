# Avoided Patterns

Common mistakes agents make in the HydraFlow codebase. These are semantic rules that linters and type checkers cannot catch — they require understanding the project's conventions and prior incidents. Read this doc before editing the areas each rule calls out.

This is the canonical location for avoided patterns. `CLAUDE.md` links here; do not duplicate rules back into `CLAUDE.md`. Sensors (`src/sensor_enricher.py`) and audit agents (`.claude/commands/hf.audit-code.md`) read this doc to coach agents during failures.

## Pydantic field additions without updating serialization tests

When you add a field to any model in `src/models.py` (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update ALL exact-match serialization tests.

- `model_dump()` assertions
- Expected key sets in smoke tests
- Any `assert result == {...}` that hard-codes the full model shape

**Why:** HydraFlow has strict exact-match tests that assert on the complete serialized dict. A new field breaks them silently during unrelated refactors, and CI flags it later as a mysterious regression.

**How to check:** After editing `models.py`, run `rg "<ModelName>" tests/` and confirm every match still passes.

## Top-level imports of optional dependencies in test files

Never write `from hindsight import Bank` at module level in tests. `httpx`, `hindsight`, and similar optional packages are not guaranteed to be installed in every environment.

**Wrong:**

```python
# tests/test_something.py
from hindsight import Bank  # module-level — fails import if hindsight not installed

class TestSomething:
    def test_x(self):
        bank = Bank()
```

**Right:**

```python
# tests/test_something.py
class TestSomething:
    def test_x(self):
        from hindsight import Bank  # deferred — only imports when the test runs
        bank = Bank()
```

**Why:** Top-level imports run at collection time. If the optional dep is missing, the entire test file fails to collect, hiding every test in it from the report.

## Spawning background sleep loops to poll for results

Never write `sleep(N)` inside a loop waiting for a test suite or background process to finish.

**Wrong:**

```python
while not result_file.exists():
    time.sleep(5)
```

**Right:**

- Use `run_in_background` with a single command and wait on the notification.
- Run the command in the foreground and await its completion directly.

**Why:** Sleep loops waste wall clock, mask failures, and provide no structured feedback. The harness exposes explicit background-task primitives for this exact purpose — use them.

## Mocking at the wrong level

Patch functions at their **import site**, not their **definition site**.

If `src/base_runner.py` contains `from hindsight import recall_safe`, then within `base_runner` the name `recall_safe` is a local binding. Patching `hindsight.recall_safe` at the definition module leaves the local binding unchanged and the mock is never hit.

**Wrong:**

```python
with patch("hindsight.recall_safe") as mock_recall:
    runner.run()  # runner's local `recall_safe` binding is unaffected
```

**Right:**

```python
with patch("base_runner.recall_safe") as mock_recall:
    runner.run()  # patches the binding the runner actually calls
```

**Why:** Python imports bind names into the importing module's namespace. A patch at the definition module only affects callers that go through that module explicitly, not callers that imported the name locally.

## Falsy checks on optional objects

Never write `if not self._hindsight` to test whether an optional object is present. Falsy checks can fire unexpectedly on mock objects, empty collections, and objects that implement `__bool__`.

**Wrong:**

```python
if not self._hindsight:
    return None
```

**Right:**

```python
if self._hindsight is None:
    return None
```

**Why:** `Mock()` objects are truthy by default, but a `Mock()` configured with `spec=SomeClass` that has `__bool__` can be falsy, and ordinary values like empty lists or dicts trigger the wrong branch. Explicit `is None` makes the intent unambiguous and matches the type annotation contract (`X | None`).

---

## Adding a new avoided pattern

When you observe a new recurring agent failure:

1. Add a new `##` section to this doc with the same structure (wrong example, right example, why).
2. Consider adding a rule to `src/sensor_rules.py` so the sensor enricher surfaces the hint automatically on matching failures.
3. Consider whether `.claude/commands/hf.audit-code.md` Agent 5 (convention drift) should check for this pattern on its next sweep.

Documenting the pattern once in this file propagates it to all three surfaces.
