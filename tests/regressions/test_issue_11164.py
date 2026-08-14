# tests/regressions/test_issue_11164.py
"""Regression pins for #11164 — the #11110 fix never fires for its own attack vector.

#11110 wired ``make console-conformance`` into CI as a step of the ``audit``
job, closing ARCH-0001's "no record modified after its creating commit"
guarantee (the git-history half that ``tests/test_console_conformance.py``
deliberately skips with ``check_git=False``).

The step exists. The job it lives in does not run for the change class the
gate was built to catch. ``audit`` is gated on
``core_python == 'true' || ci == 'true'``, and ``core_python``'s include
brace-glob has no ``agents/**`` entry — the ledger lives at
``agents/console/decisions/**``. Only the separate ``python`` filter output
lists ``agents/**``, and ``audit`` never reads ``python``. So a PR that
silently rewrites a merged decision record — the scenario #11110 was filed
against — sets ``python=true``, ``core_python=false``, ``ci=false``, skips the
whole ``audit`` job, and merges green with the immutability check never
executed.

The pin shipped with #11110 (``test_ci_audit_job_runs_console_conformance``)
asserts the step is present in the job's step list and that checkout keeps
``fetch-depth: 0``. It never evaluates the job's ``if:`` against a changed-file
set, so it stayed green across this entire gap.

These tests evaluate the real ci.yml the way ``dorny/paths-filter`` does:
expand each filter's globs, match them against a representative changed-file
path, and ask whether a job that runs ``make console-conformance`` would
actually be triggered.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO = Path(__file__).resolve().parent.parent.parent
_CI = _REPO / ".github" / "workflows" / "ci.yml"

# The attack vector in ARCH-0001's own words: a merged decision record edited
# after its creating commit. This file is real and tracked.
LEDGER_EDIT = "agents/console/decisions/arch/0001-console-charter.md"


def _load_ci() -> dict[str, Any]:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _brace_expand(pattern: str) -> list[str]:
    """Expand a single (non-nested) ``{a,b,c}`` group, as micromatch does."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    expanded: list[str] = []
    for alt in match.group(1).split(","):
        expanded.extend(
            _brace_expand(pattern[: match.start()] + alt + pattern[match.end() :])
        )
    return expanded


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a paths-filter glob to a regex with micromatch-ish semantics."""
    out = ""
    i = 0
    while i < len(glob):
        char = glob[i]
        if glob.startswith("**/", i):
            out += "(?:[^/]+/)*"
            i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out += "/.*"
            i += 3
        elif glob.startswith("**", i):
            out += ".*"
            i += 2
        elif char == "*":
            out += "[^/]*"
            i += 1
        elif char == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(char)
            i += 1
    return re.compile(f"^{out}$")


def _matches_any(path: str, globs: list[str]) -> bool:
    return any(
        _glob_to_regex(expanded).match(path)
        for glob in globs
        for expanded in _brace_expand(glob)
    )


def _filter_fires(path: str, patterns: list[str], quantifier: str) -> bool:
    """Evaluate one paths-filter entry against a single changed path."""
    positives = [p for p in patterns if not p.startswith("!")]
    negatives = [p[1:] for p in patterns if p.startswith("!")]
    if quantifier == "every":
        # Every pattern must hold: inside all includes, outside all negations.
        return _matches_any(path, positives) and not _matches_any(path, negatives)
    # Default `some`: any single pattern matching is enough.
    return _matches_any(path, positives)


def _changes_outputs(ci: dict[str, Any]) -> dict[str, tuple[list[str], str]]:
    """Map each ``changes`` job output to (globs, predicate-quantifier)."""
    changes = ci["jobs"]["changes"]
    by_step_id: dict[str, tuple[dict[str, Any], str]] = {}
    for step in changes["steps"]:
        if "paths-filter" not in str(step.get("uses", "")):
            continue
        with_block = step.get("with", {})
        parsed = yaml.safe_load(with_block["filters"])
        quantifier = str(with_block.get("predicate-quantifier", "some"))
        by_step_id[str(step["id"])] = (parsed, quantifier)

    resolved: dict[str, tuple[list[str], str]] = {}
    for name, expr in changes["outputs"].items():
        ref = re.search(r"steps\.(\w+)\.outputs\.(\w+)", str(expr))
        assert ref, f"unparsable `changes` output expression for {name!r}: {expr!r}"
        filters, quantifier = by_step_id[ref.group(1)]
        resolved[str(name)] = (list(filters[ref.group(2)]), quantifier)
    return resolved


def _job_gate_outputs(ci: dict[str, Any], job: str) -> list[str]:
    """The ``needs.changes.outputs.X`` names a job's ``if:`` condition reads."""
    condition = str(ci["jobs"][job].get("if", ""))
    return re.findall(r"needs\.changes\.outputs\.(\w+)", condition)


def test_filter_evaluator_agrees_with_known_ci_behaviour() -> None:
    """Counter-pin: the RED assertions below are only worth anything if this
    evaluator reproduces filter outcomes CI is already known to produce.

    Each case here is an outcome ci.yml's own comments assert independently —
    the ``core_python`` negations (#9908) and the ``ci`` filter. If the glob
    translation were simply broken, these would fail too.
    """
    outputs = _changes_outputs(_load_ci())

    def fires(path: str, name: str) -> bool:
        return _filter_fires(path, *outputs[name])

    # Ordinary source and test edits drive the core lane.
    assert fires("src/orchestrator.py", "core_python")
    assert fires("src/orchestrator.py", "python")
    assert fires("tests/test_console_conformance.py", "core_python")
    # The `every`-quantifier negations subtract, rather than matching everything
    # outside a single negated dir (#9908's regression).
    assert not fires("tests/regressions/test_issue_11164.py", "core_python")
    assert fires("tests/regressions/test_issue_11164.py", "python")
    assert not fires(
        "docs/adr/0042-two-tier-branch-release-promotion.md", "core_python"
    )
    # Workflow edits drive `ci`; ledger edits do not.
    assert fires(".github/workflows/ci.yml", "ci")
    assert not fires(LEDGER_EDIT, "ci")
    # `python` carries the `agents/**` entry; `core_python`'s brace-glob does not.
    assert fires(LEDGER_EDIT, "python")
    assert not fires(LEDGER_EDIT, "core_python")


def _console_conformance_jobs(ci: dict[str, Any]) -> list[str]:
    return [
        name
        for name, job in ci["jobs"].items()
        if any(
            "make console-conformance" in str(step.get("run", ""))
            for step in job.get("steps", [])
        )
    ]


def _full_history_jobs(ci: dict[str, Any]) -> list[str]:
    return sorted(
        name
        for name, job in ci["jobs"].items()
        if any(
            "checkout" in str(step.get("uses", ""))
            and step.get("with", {}).get("fetch-depth") == 0
            for step in job.get("steps", [])
        )
    )


def test_console_conformance_runs_for_a_decision_record_only_change() -> None:
    """The step must exist AND live in a job a ledger-only PR actually triggers.

    The #11110 pin proves only the first half. Both halves have to hold for
    ARCH-0001's ``Enforced by: make console-conformance`` to be true.

    Deliberately remedy-agnostic: gating ``audit`` on ``python`` too, adding
    ``agents/**`` to ``core_python``, adding a dedicated filter output OR'd
    into ``audit``'s ``if:``, or moving the step to another full-history job
    whose filter covers ``agents/**`` all satisfy this.
    """
    ci = _load_ci()
    outputs = _changes_outputs(ci)

    hosting = _console_conformance_jobs(ci)
    assert hosting, "no CI job runs `make console-conformance` at all (#11110)"

    gates = {name: _job_gate_outputs(ci, name) for name in hosting}
    reachable = [
        name
        for name, names in gates.items()
        if any(_filter_fires(LEDGER_EDIT, *outputs[g]) for g in names if g in outputs)
    ]
    detail = {
        name: {
            g: _filter_fires(LEDGER_EDIT, *outputs[g]) for g in names if g in outputs
        }
        for name, names in gates.items()
    }
    assert reachable, (
        f"`make console-conformance` runs only in {hosting}, and no such job is "
        f"triggered by a PR that changes only {LEDGER_EDIT} — the exact "
        "'silently rewritten decision record' scenario #11110 was filed "
        f"against. Gate evaluation: {detail}. The `python` output DOES cover "
        "the ledger (it lists 'agents/**' for precisely this reason): "
        f"{_filter_fires(LEDGER_EDIT, *outputs['python'])} — but no hosting job "
        "reads it, so the immutability half of ARCH-0001 is enforced nowhere "
        "for ledger-only PRs (#11164)."
    )


def test_ledger_only_change_does_not_trigger_heavy_lanes() -> None:
    """The fix must be surgical: making `audit` reachable for agents/**-only
    PRs must not also newly trigger the heavy core_python-gated lanes
    (smoke/scenario/regression/sandbox). Widening `core_python` itself would
    have "fixed" the reachability gap too, but at the cost of dragging every
    decision-record edit through those lanes — the tempting-but-wrong remedy
    the plan for #11164 explicitly rejected.
    """
    ci = _load_ci()
    outputs = _changes_outputs(ci)
    heavy_lanes = ("smoke", "scenario", "regression", "sandbox-fast")
    present = [name for name in heavy_lanes if name in ci["jobs"]]
    assert present, "none of the expected heavy-lane job names exist in ci.yml"

    triggered = [
        name
        for name in present
        if any(
            _filter_fires(LEDGER_EDIT, *outputs[g])
            for g in _job_gate_outputs(ci, name)
            if g in outputs
        )
    ]
    assert not triggered, (
        f"a ledger-only PR ({LEDGER_EDIT}) newly triggers heavy lane(s) "
        f"{triggered} — the console_ledger filter must stay narrowly scoped "
        "to agents/**, not widen core_python or any lane gated by it (#11164)"
    )


def test_full_history_uniqueness_claim_in_ci_is_true() -> None:
    """ci.yml must not justify a step's placement with a false uniqueness claim.

    A prior comment claimed the `audit` job "uniquely" already has
    ``fetch-depth: 0``. The `arch` job (Architecture Check) checks out with
    ``fetch-depth: 0`` as well, so any surviving "uniquely" claim about a
    full-history checkout must actually be true of the parsed workflow.

    Satisfied by correcting the comment or by relocating the step; this pins
    the claim against reality, not any one wording.
    """
    ci = _load_ci()
    raw = _CI.read_text(encoding="utf-8")
    claims = [
        line.strip()
        for line in raw.splitlines()
        if "#" in line and "uniquely" in line and "fetch-depth" in line
    ]
    if not claims:
        return  # no uniqueness claim to keep honest

    full_history = _full_history_jobs(ci)
    assert len(full_history) == 1, (
        f"ci.yml claims a job uniquely has a full-history checkout ({claims}), "
        f"but these jobs use fetch-depth: 0 — {full_history}. Either the "
        "comment is wrong or the placement rationale needs restating (#11164)."
    )
