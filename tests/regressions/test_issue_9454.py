"""Regression for issue #9454 — unbounded ``await proc.communicate()`` sweep.

Issue #9410 root-caused a *permanent* silent stall of ``TrustFleetSanityLoop``
to an unbounded ``await proc.communicate()`` after
``asyncio.create_subprocess_exec``: if the ``gh`` child wedges (auth prompt,
network black-hole, hung process), the await never returns, the work cycle
never advances its heartbeat, and the orchestrator supervisor — which only
wakes on task *completion* — never restarts the dead loop.

Issue #9454 observes the same latent bug in ~10 other caretaker loops whose
``proc.communicate()`` calls are NOT bounded. Each is a ``git``/``gh``/``make``
subprocess that, if it wedges, hangs that loop's work cycle indefinitely and
freezes its heartbeat. The desired behavior (matching the hardened reference
sites ``contract_refresh_loop.py`` and ``staging_bisect_loop.py``) is that
*every* async ``communicate()`` in loop code is bounded — by
``asyncio.wait_for(proc.communicate(), timeout=...)`` with a ``proc.kill()``
fallback, or by the ``asyncio.create_task(proc.communicate())`` + deadline-loop
form already used in ``staging_bisect_loop._run_git``.

This is a static-analysis regression in the spirit of
``test_async_subprocess_timeouts.py`` (which enforces ``timeout=`` on
``subprocess.run``). It parses each cited module and asserts no ``communicate()``
call is left unbounded. It is RED against current code: every module below still
has at least one bare ``await proc.communicate()``.

The list below is the source of truth for which loops the #9454 sweep must
harden; when a loop is fixed it should *stay* in this list (a green case),
mirroring the ``_ASYNC_SUBPROCESS_MODULES`` allowlist convention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent

# Caretaker loops cited in #9454 with unbounded ``await proc.communicate()``.
# ``trust_fleet_sanity_loop.py`` is excluded — it was the #9410 fix and is
# already hardened. ``contract_refresh_loop.py`` is the hardened reference.
#
# ``wiki_rot_detector_loop.py`` was cited in the original sweep but has *no*
# direct subprocess: its only ``gh issue list`` read goes through the
# ``PRManager`` port (``self._pr.list_closed_issues_by_label``), so the module
# contains no ``proc.communicate()`` to harden. It is therefore a
# false-positive against the ``assert communicate_count`` guard below. The
# fleet-wide AST scan in ``test_issue_9508.py`` is the authoritative source of
# truth and correctly does not flag it.
_UNHARDENED_COMMUNICATE_MODULES = [
    "src/corpus_learning_loop.py",
    "src/memory_backlog_loop.py",
    "src/adr_touchpoint_auditor_loop.py",
    "src/rc_budget_loop.py",
    "src/skill_prompt_eval_loop.py",
    "src/principles_audit_loop.py",
    "src/fake_coverage_auditor_loop.py",
    "src/flake_tracker_loop.py",
    "src/staging_bisect_loop.py",
]

# A ``communicate()`` call is considered *bounded* when it is a direct argument
# to one of these. ``wait_for`` is the canonical fix; ``create_task`` is the
# deadline-loop form used by ``staging_bisect_loop._run_git`` (the task is
# subsequently awaited under an ``asyncio.wait(..., timeout=...)`` deadline).
_BOUNDING_CALLS = {"wait_for", "create_task"}


def _callee_name(func: ast.expr) -> str | None:
    """Return the trailing name of a call target.

    ``asyncio.wait_for`` -> ``"wait_for"``; bare ``wait_for`` -> ``"wait_for"``.
    """
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_communicate_call(node: ast.AST) -> bool:
    """True for ``<expr>.communicate(...)`` call nodes."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "communicate"
    )


def _unbounded_communicate_lines(src: str) -> list[int]:
    """Line numbers of every ``communicate()`` call not bounded by wait_for/create_task."""
    tree = ast.parse(src)
    bounded: set[int] = set()  # id() of communicate Call nodes that are bounded
    all_calls: list[ast.Call] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_communicate_call(node):
            all_calls.append(node)
        if _callee_name(node.func) in _BOUNDING_CALLS:
            for arg in node.args:
                if _is_communicate_call(arg):
                    bounded.add(id(arg))

    return sorted(n.lineno for n in all_calls if id(n) not in bounded)


@pytest.mark.parametrize("rel_path", _UNHARDENED_COMMUNICATE_MODULES)
def test_async_communicate_is_bounded(rel_path: str) -> None:
    """Every async ``proc.communicate()`` in this loop must be bounded.

    Unbounded ``await proc.communicate()`` lets a wedged subprocess hang the
    loop's work cycle forever, freezing its heartbeat (same failure class as
    issue #9410 / ``TrustFleetSanityLoop``).
    """
    path = _REPO / rel_path
    src = path.read_text()
    communicate_count = sum(
        1 for n in ast.walk(ast.parse(src)) if _is_communicate_call(n)
    )
    assert communicate_count, f"{rel_path} has no proc.communicate() calls"

    unbounded = _unbounded_communicate_lines(src)
    assert not unbounded, (
        f"{rel_path}: {len(unbounded)} of {communicate_count} proc.communicate() "
        f"call(s) are NOT bounded by asyncio.wait_for/create_task "
        f"(lines {unbounded}). An unbounded await proc.communicate() lets a "
        f"wedged git/gh/make subprocess hang the loop cycle indefinitely and "
        f"freeze its heartbeat — the #9410 silent-stall failure class. Wrap in "
        f"asyncio.wait_for(proc.communicate(), timeout=...) with a proc.kill() "
        f"fallback (see contract_refresh_loop.py / staging_bisect_loop.py)."
    )
