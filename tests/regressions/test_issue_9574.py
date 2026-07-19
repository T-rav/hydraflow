"""Regression test for issue #9574.

Bug: ``ADRPreValidator._check_source_function_refs`` only verified
single-segment source symbols.  ``_SOURCE_SYMBOL_RE`` captured only
``[A-Za-z_]\\w*`` in the symbol position, so a dotted method-level citation
like ``src/foo.py:Class.method`` matched NOTHING and was silently skipped.
A citation naming a nonexistent method therefore passed validation.

Expected behaviour after fix:
  - A dotted citation naming a REAL class but a NONEXISTENT method
    (``src/adr_pre_validator.py:ADRPreValidator.typo_method``) is flagged
    as ``phantom_source_symbol``.
  - A dotted citation naming a REAL class AND a REAL method
    (``src/adr_pre_validator.py:ADRPreValidator.validate``) is NOT flagged.

The first assertion is RED against the current (buggy) code: the dotted
citation is skipped entirely, so no phantom_source_symbol issue is raised.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from adr_pre_validator import ADRPreValidator


def _valid_adr(*, context: str) -> str:
    return f"""# ADR-0001: Test ADR

**Status:** Proposed

## Context

{context}

## Decision

We decided to do the thing.

## Consequences

Some consequences.
"""


@pytest.fixture
def validator() -> ADRPreValidator:
    return ADRPreValidator()


class TestIssue9574DottedSourceCitations:
    def test_dotted_citation_to_nonexistent_method_is_flagged(
        self, validator: ADRPreValidator
    ) -> None:
        """A real class with a typo'd method name is flagged as a phantom symbol."""
        content = _valid_adr(
            context=(
                "See `src/adr_pre_validator.py:ADRPreValidator.typo_method` "
                "for details."
            )
        )
        result = validator.validate(content, repo_root=_REPO_ROOT)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" in codes
        issue = next(i for i in result.issues if i.code == "phantom_source_symbol")
        assert "typo_method" in issue.message

    def test_dotted_citation_to_real_method_is_not_flagged(
        self, validator: ADRPreValidator
    ) -> None:
        """A real class with a real method is NOT flagged (no false positive)."""
        content = _valid_adr(
            context=(
                "See `src/adr_pre_validator.py:ADRPreValidator.validate` for details."
            )
        )
        result = validator.validate(content, repo_root=_REPO_ROOT)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes
