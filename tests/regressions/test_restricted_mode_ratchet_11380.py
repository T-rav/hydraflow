"""Regression pins for the #11380 restricted-mode declaration ratchet.

The ADR-0092 family (#11374) was being discovered one call site at a time
by finder sweeps — each filing a separate issue. The guard replaces that
with a mechanical burn-down: an undeclared new site fails CI, and the
baseline can only shrink.

Pins:
1. The guard's scanner actually detects an undeclared call (it would be
   vacuous if the AST walk missed the shape).
2. The two highest-risk untrusted-text spawns hardened in this change stay
   hardened (diagnostic Stage-1/2 reads issue body + CI logs; bug
   reproducer reads the reporter's claim verbatim).
"""

from __future__ import annotations

import ast

from tests.architecture.test_restricted_mode_declaration import (
    GRANDFATHERED_UNDECLARED,
    _enclosing_function,
    _undeclared_sites,
)


def test_scanner_detects_an_undeclared_call() -> None:
    """Guard against a vacuous scanner: the AST shape must be matched."""
    source = (
        "def _build_command(self):\n"
        "    return build_agent_command(tool='claude', model='m')\n"
    )
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "build_agent_command"
    ]
    assert len(calls) == 1
    assert not any(kw.arg == "restricted" for kw in calls[0].keywords)
    assert _enclosing_function(tree, calls[0]) == "_build_command"


def test_untrusted_text_spawns_are_hardened() -> None:
    """These read attacker-influencable text — they must never regress."""
    undeclared = _undeclared_sites()
    for site in (
        "src/diagnostic_runner.py::_build_command",
        "src/bug_reproducer.py::_build_command",
    ):
        assert site not in undeclared
        assert site not in GRANDFATHERED_UNDECLARED


def test_baseline_only_shrinks_from_here() -> None:
    """The ratchet's contract, pinned: today's baseline is the ceiling."""
    assert len(GRANDFATHERED_UNDECLARED) <= 18
