"""Tests for sensor_enricher — enrichment of tool output with agent hints.

Covers the matching engine (:func:`matching_rules`) and the public
:func:`enrich` facade. Uses hand-crafted rules so tests do not depend on
the seed registry drift.

Part of the harness-engineering foundations (#6426).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sensor_enricher import (
    ANY_TOOL,
    ErrorPattern,
    FileChanged,
    Rule,
    enrich,
    matching_rules,
)


def _mk_rule(
    rule_id: str,
    tool: str,
    trigger: FileChanged | ErrorPattern,
    hint: str = "hint body",
) -> Rule:
    return Rule(id=rule_id, tool=tool, trigger=trigger, hint=hint)


# ---------------------------------------------------------------------------
# FileChanged trigger
# ---------------------------------------------------------------------------


class TestFileChangedTrigger:
    def test_exact_file_match(self) -> None:
        trigger = FileChanged("src/models.py")
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/models.py")],
        )

    def test_glob_match(self) -> None:
        trigger = FileChanged("src/*_loop.py")
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/code_grooming_loop.py")],
        )

    def test_no_match_when_unrelated_file(self) -> None:
        trigger = FileChanged("src/models.py")
        assert not trigger.matches(
            raw_output="",
            changed_files=[Path("src/agent.py")],
        )

    def test_no_match_with_empty_file_list(self) -> None:
        trigger = FileChanged("src/*.py")
        assert not trigger.matches(raw_output="", changed_files=[])

    def test_posix_path_conversion(self) -> None:
        """Windows-style paths should still match POSIX globs."""
        trigger = FileChanged("src/models.py")
        # PurePath.as_posix() normalizes separators regardless of OS.
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/models.py")],
        )


# ---------------------------------------------------------------------------
# ErrorPattern trigger
# ---------------------------------------------------------------------------


class TestErrorPatternTrigger:
    def test_regex_match_single_line(self) -> None:
        trigger = ErrorPattern(r"ModuleNotFoundError.*hindsight")
        assert trigger.matches(
            raw_output="ModuleNotFoundError: No module named 'hindsight'",
            changed_files=[],
        )

    def test_regex_match_multiline(self) -> None:
        trigger = ErrorPattern(r"^ERROR:")
        output = "warning: something\nERROR: boom\n"
        assert trigger.matches(raw_output=output, changed_files=[])

    def test_no_match(self) -> None:
        trigger = ErrorPattern(r"KeyError")
        assert not trigger.matches(
            raw_output="TypeError: bad thing",
            changed_files=[],
        )


# ---------------------------------------------------------------------------
# matching_rules
# ---------------------------------------------------------------------------


class TestMatchingRules:
    def test_tool_filter_respected(self) -> None:
        rule = _mk_rule("pytest-only", "pytest", ErrorPattern("boom"))
        result = matching_rules(
            [rule],
            tool="ruff",
            raw_output="boom",
            changed_files=[],
        )
        assert not result
        assert result.fired == []

    def test_any_tool_matches_any_tool(self) -> None:
        rule = _mk_rule("universal", ANY_TOOL, ErrorPattern("boom"))
        for tool in ("pytest", "ruff", "pyright", "bandit"):
            result = matching_rules(
                [rule],
                tool=tool,
                raw_output="boom",
                changed_files=[],
            )
            assert result.fired == [rule]

    def test_multiple_rules_all_fire(self) -> None:
        rule_a = _mk_rule("a", ANY_TOOL, ErrorPattern("boom"))
        rule_b = _mk_rule("b", ANY_TOOL, FileChanged("src/models.py"))
        result = matching_rules(
            [rule_a, rule_b],
            tool="pytest",
            raw_output="boom",
            changed_files=[Path("src/models.py")],
        )
        assert result.fired == [rule_a, rule_b]

    def test_no_match_returns_empty_falsy_result(self) -> None:
        rule = _mk_rule("a", "pytest", ErrorPattern("KeyError"))
        result = matching_rules(
            [rule],
            tool="pytest",
            raw_output="TypeError: bad",
            changed_files=[],
        )
        assert not result
        assert result.fired == []

    def test_empty_rule_list_returns_empty_result(self) -> None:
        result = matching_rules(
            [],
            tool="pytest",
            raw_output="anything",
            changed_files=[],
        )
        assert not result


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------


class TestEnrich:
    def test_no_match_returns_raw_output_unchanged(self) -> None:
        rule = _mk_rule("a", "pytest", ErrorPattern("KeyError"))
        raw = "TypeError: bad thing"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[],
            rules=[rule],
        )
        assert result == raw

    def test_match_appends_hints_block(self) -> None:
        rule = _mk_rule(
            "a",
            "pytest",
            ErrorPattern("boom"),
            hint="Check the foo.",
        )
        raw = "test_x FAILED\nboom happened"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[],
            rules=[rule],
        )
        assert raw in result
        assert "## Agent Hints" in result
        assert "- Check the foo." in result

    def test_raw_output_preserved_verbatim(self) -> None:
        """Hints are additive — raw output must not be modified."""
        rule = _mk_rule(
            "a",
            ANY_TOOL,
            FileChanged("src/models.py"),
            hint="A hint.",
        )
        raw = "line1\n  indented line\nline3"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[Path("src/models.py")],
            rules=[rule],
        )
        assert result.startswith(raw + "\n\n")

    def test_multiple_hints_listed_as_bullets(self) -> None:
        rule_a = _mk_rule("a", ANY_TOOL, ErrorPattern("boom"), hint="Hint A.")
        rule_b = _mk_rule("b", ANY_TOOL, ErrorPattern("boom"), hint="Hint B.")
        result = enrich(
            tool="pytest",
            raw_output="boom",
            changed_files=[],
            rules=[rule_a, rule_b],
        )
        assert "- Hint A." in result
        assert "- Hint B." in result

    def test_empty_rules_returns_raw_output(self) -> None:
        raw = "anything"
        assert (
            enrich(
                tool="pytest",
                raw_output=raw,
                changed_files=[],
                rules=[],
            )
            == raw
        )


# ---------------------------------------------------------------------------
# Seed rule registry smoke test
# ---------------------------------------------------------------------------


class TestSeedRules:
    """Sanity checks on the seed registry — catches drift from the doc."""

    def test_seed_registry_loads(self) -> None:
        from sensor_rules import SEED_RULES

        assert len(SEED_RULES) >= 5, "seed registry must cover all known patterns"

    def test_seed_rule_ids_unique(self) -> None:
        from sensor_rules import SEED_RULES

        ids = [r.id for r in SEED_RULES]
        assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"

    def test_seed_rules_reference_avoided_patterns_doc(self) -> None:
        from sensor_rules import SEED_RULES

        # Every hint should point at the canonical doc so rule text stays
        # consistent with the human-facing rule descriptions.
        for rule in SEED_RULES:
            assert (
                "docs/agents/avoided-patterns.md" in rule.hint
                or "CLAUDE.md" in rule.hint
            ), f"rule {rule.id} has no doc reference"

    def test_pydantic_rule_fires_for_models_edit(self) -> None:
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output="",
            changed_files=[Path("src/models.py")],
        )
        rule_ids = {r.id for r in result.fired}
        assert "pydantic-field-tests" in rule_ids

    def test_optional_dep_rule_fires_for_hindsight_import_error(self) -> None:
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output="ModuleNotFoundError: No module named 'hindsight'",
            changed_files=[],
        )
        rule_ids = {r.id for r in result.fired}
        assert "optional-dep-toplevel-import" in rule_ids
