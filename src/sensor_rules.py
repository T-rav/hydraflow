"""Seed rule registry for :mod:`sensor_enricher`.

Each rule is a triple of (id, trigger, hint). Rules fire when tool
output is captured from a subprocess and match either a file-change
pattern or an error-regex pattern.

Rules seeded here mirror the rule bullets in
``docs/agents/avoided-patterns.md``. Adding a new avoided pattern?
Add both a section to that doc AND a rule here — the sensor enricher
will surface the hint the next time the matching failure occurs.

Part of the harness-engineering foundations (#6426).
"""

from __future__ import annotations

from sensor_enricher import ANY_TOOL, ErrorPattern, FileChanged, Rule

__all__ = ["SEED_RULES"]


SEED_RULES: list[Rule] = [
    Rule(
        id="pydantic-field-tests",
        tool=ANY_TOOL,
        trigger=FileChanged("src/models.py"),
        hint=(
            "You modified `src/models.py`. Pydantic field additions "
            "commonly break exact-match serialization tests. Grep `tests/` "
            "for the model name and update `model_dump()` assertions and "
            "expected-key sets in smoke tests. "
            "See docs/agents/avoided-patterns.md — 'Pydantic field "
            "additions without updating serialization tests'."
        ),
    ),
    Rule(
        id="optional-dep-toplevel-import",
        tool="pytest",
        trigger=ErrorPattern(
            r"ModuleNotFoundError.*(hindsight|httpx)"
            r"|ImportError.*(hindsight|httpx)"
        ),
        hint=(
            "An optional dependency (hindsight/httpx) failed to import at "
            "collection time. Move the import inside the test method "
            "instead of a module-level `from ... import ...`. "
            "See docs/agents/avoided-patterns.md — 'Top-level imports of "
            "optional dependencies in test files'."
        ),
    ),
    Rule(
        id="background-loop-wiring",
        tool=ANY_TOOL,
        trigger=FileChanged("src/*_loop.py"),
        hint=(
            "You modified a background loop module. The wiring "
            "completeness test (tests/test_loop_wiring_completeness.py) "
            "enforces entries in src/service_registry.py, src/orchestrator.py, "
            "src/ui/src/constants.js, src/dashboard_routes/_common.py, and "
            "src/config.py. Confirm all five are updated before committing. "
            "See CLAUDE.md — 'Background Loop Guidelines'."
        ),
    ),
    Rule(
        id="mock-wrong-patch-site",
        tool="pytest",
        trigger=ErrorPattern(
            r"AssertionError.*call_count|assert.*called_with|"
            r"AttributeError.*Mock object has no attribute"
        ),
        hint=(
            "Mock assertion failures often indicate patching at the wrong "
            "level. Patch functions at their IMPORT site (the module that "
            "does `from X import Y`), not at their DEFINITION site (module "
            "X itself). Python imports bind names into the importing "
            "module's namespace; a patch at the definition site does not "
            "affect local bindings. "
            "See docs/agents/avoided-patterns.md — 'Mocking at the wrong level'."
        ),
    ),
    Rule(
        id="falsy-optional-check",
        tool="pytest",
        trigger=ErrorPattern(
            r"assert.*is None|AttributeError.*NoneType|"
            r"TypeError.*NoneType"
        ),
        hint=(
            "Optional-attribute errors often come from `if not self._x` "
            "style falsy checks on values typed `X | None`. Mock objects "
            "are truthy by default, and some objects implement `__bool__`, "
            "so the falsy branch does not fire reliably. Use explicit "
            "`if self._x is None:` instead. "
            "See docs/agents/avoided-patterns.md — 'Falsy checks on "
            "optional objects'."
        ),
    ),
]
