"""Ratchet: every ``build_agent_command`` call site declares ``restricted=``.

ADR-0092 hardens issue-derived spawns against prompt injection by swapping
blanket ``bypassPermissions`` for ``acceptEdits`` + an explicit allowlist and
disallowing network-egress tools. The parameter defaults to ``False``, so a
new spawn that processes untrusted issue/PR/CI text is permissive **by
omission** — nothing fails, nobody notices. An overnight finder sweep filed
per-site issues for exactly this (folded into the #11374 class canonical);
this guard replaces that per-site filing with a mechanical burn-down.

The rule: every call site must pass ``restricted=`` EXPLICITLY — ``True``
when the spawn sees untrusted content, ``False`` (a deliberate, reviewable
declaration) when it does not. Sites predating the guard are grandfathered
below and the ratchet only shrinks: a new undeclared site fails CI, and a
resolved site must be pruned from the baseline in the same change.
"""

from __future__ import annotations

import ast
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"

#: Call sites that do not yet declare ``restricted=``, keyed
#: ``"<repo-relative path>::<enclosing function>"``. DO NOT ADD ENTRIES —
#: a new ``build_agent_command`` call declares the parameter instead.
#: Remove entries as sites are hardened; the ratchet only shrinks.
GRANDFATHERED_UNDECLARED: frozenset[str] = frozenset(
    {
        "src/acceptance_criteria.py::_build_command",
        "src/agent/_prequality.py::_build_pre_quality_review_command",
        "src/agent/_skills.py::_run_skill_verifier",
        "src/discover_runner.py::_build_command",
        "src/implement_spec_reviewer.py::run",
        "src/plan_reviewer.py::_build_command",
        "src/planner.py::_build_command",
        "src/precheck.py::build_debug_command",
        "src/precheck.py::build_subskill_command",
        "src/report_issue_loop.py::_do_work",
        "src/research_runner.py::_build_command",
        "src/review_phase/_advisors.py::_run_pre_merge_spec_check",
        "src/review_phase/_advisors.py::run",
        "src/reviewer/_prompts.py::_build_command",
        "src/shape_runner.py::_build_command",
        "src/triage.py::_build_command",
        "src/ultra_review.py::build_ultra_review_command",
        "src/verification_judge.py::_build_command",
    }
)


def _enclosing_function(tree: ast.AST, target: ast.AST) -> str:
    """Name of the innermost function containing *target* (else '<module>')."""
    best = "<module>"
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        t_line = getattr(target, "lineno", 0)
        if start <= t_line <= end:
            best = node.name
    return best


def _undeclared_sites() -> set[str]:
    """Scan src/ for ``build_agent_command`` calls lacking ``restricted=``."""
    undeclared: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        if path.name == "agent_cli.py":  # the definition itself
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "build_agent_command":
                continue
            if any(kw.arg == "restricted" for kw in node.keywords):
                continue
            rel = path.relative_to(_REPO).as_posix()
            undeclared.add(f"{rel}::{_enclosing_function(tree, node)}")
    return undeclared


def test_no_new_undeclared_restricted_sites() -> None:
    """A new build_agent_command call must declare ``restricted=``."""
    new = _undeclared_sites() - GRANDFATHERED_UNDECLARED
    assert not new, (
        "build_agent_command call site(s) without an explicit `restricted=` "
        f"declaration: {sorted(new)}. ADR-0092: a spawn that reads untrusted "
        "issue/PR/CI text must pass restricted=True; one that does not must "
        "say restricted=False deliberately. Do NOT grow "
        "GRANDFATHERED_UNDECLARED — the ratchet only shrinks."
    )


def test_baseline_has_no_stale_entries() -> None:
    """A hardened site must be pruned from the baseline in the same change."""
    stale = GRANDFATHERED_UNDECLARED - _undeclared_sites()
    assert not stale, (
        f"Baseline entries no longer undeclared: {sorted(stale)}. "
        "Prune them — the ratchet only shrinks."
    )


def test_untrusted_content_runners_are_hardened() -> None:
    """The spawns that read issue-derived text MUST already be restricted.

    These are the ADR-0092 originals — the guard pins them so a refactor
    cannot silently drop hardening from the highest-risk paths.
    """
    undeclared = _undeclared_sites()
    for site in (
        "src/preflight/auto_agent_runner.py::_build_command",
        "src/goal_supervisor_runner.py::_build_command",
    ):
        assert site not in undeclared, (
            f"{site} lost its restricted= declaration — this spawn reads "
            "untrusted issue content (ADR-0092)."
        )
