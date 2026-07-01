"""Tests for the Enforcement injector in the ADR council writer.

Closes the gap where bot-authored ADRs flipped to Accepted without an
``**Enforcement:**`` line, which would then fail the ADR-0098 coverage
ratchet (``tests/test_adr_conformance_coverage.py``). Supersedes the
pre-ADR-0098 "P3" convention (PR #8398), which only guaranteed a bare
``**Enforced by:** (none)`` line validated by the now-deleted
``tests/test_adr_enforcement.py``.
"""

from __future__ import annotations

from adr_reviewer import _ensure_enforcement_line


def test_injects_decision_of_record_when_absent() -> None:
    content = (
        "# ADR-0099: Test ADR\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-04-24\n\n"
        "## Context\n\nSomething.\n"
    )
    result = _ensure_enforcement_line(content)
    assert "**Enforcement:** decision-of-record" in result
    # Must land directly under Status, not elsewhere
    status_idx = result.index("**Status:**")
    enforcement_idx = result.index("**Enforcement:**")
    date_idx = result.index("**Date:**")
    assert status_idx < enforcement_idx < date_idx


def test_preserves_existing_enforcement() -> None:
    """If the author already provided a line, don't overwrite it."""
    content = (
        "# ADR-0099: Test\n\n"
        "**Status:** Accepted\n"
        "**Enforcement:** enforced\n"
        "**Enforced by:** pytest:tests/test_foo.py\n"
        "**Date:** 2026-04-24\n\n"
        "## Context\n\nYes.\n"
    )
    result = _ensure_enforcement_line(content)

    assert "**Enforcement:** enforced" in result
    assert "decision-of-record" not in result
    # Only one Enforcement line, not two.
    assert result.count("**Enforcement:**") == 1


def test_no_status_line_leaves_content_untouched() -> None:
    """Malformed ADR (no Status line) shouldn't crash — just pass through."""
    content = "# ADR-0099: Malformed\n\nNo status line present.\n"
    result = _ensure_enforcement_line(content)
    assert result == content
