"""Guard: a workflow change must not orphan a branch-protection required check.

`make gen-gates-check` already validates that every required gate's declared
producer *job key* exists in its workflow (`scripts/gates/validate.py`). But it
is deliberately blind to matrix expansion — it matches the job KEY, not the
GitHub check *context*. That leaves one orphaning vector uncovered: the
`quality (<project_dir>)` contexts are matrix legs whose values come from the
DYNAMIC `discover-projects` scan in `quality.yml` (a `${{ fromJSON(...) }}`
matrix), not a static list. An edit to that scan — dropping a marker file from
the `markers` set, adding a required dir to `ignored`, or deleting the marker
file itself — silently stops producing e.g. `quality (.)`. Branch protection
still *requires* that context, so it sits "expected / never reported" forever
and jams the whole merge queue with no red X to point at (the class of foot-gun
that was caught only by a human reading a diff on 2026-07-21; issue #10142).

This guard ties the required matrix contexts back to the scan that must produce
them, so such an edit fails a required check (`Tests`) instead of merging.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml
from scripts.gates.contract import Gate, load_gates
from scripts.gates.resolve import resolve_contexts

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_TOML = _REPO_ROOT / "docs" / "standards" / "branch_protection" / "gates.toml"
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_QUALITY_WF = _WORKFLOW_DIR / "quality.yml"

# Non-marker suffixes discover-projects also treats as project markers.
_MARKER_SUFFIXES = {".sln", ".csproj"}
# Only the `quality` job carries a dynamic matrix today. If a NEW matrix job
# becomes a required producer, this guard must be extended to verify its matrix
# values too — `test_no_unknown_matrix_producer` fails loudly to force that.
_KNOWN_MATRIX_JOB = "quality"
# A matrix-expanded context is "<job-name> (<matrix value>)".
_MATRIX_CONTEXT_RE = re.compile(r"^\S.*? \((?P<value>.+)\)$")


def _required_gates() -> list[Gate]:
    """Gates whose context is required on at least one protected branch."""
    contract = load_gates(_GATES_TOML)
    required_names: set[str] = set()
    for branch in ("main", "staging"):
        required_names.update(resolve_contexts(contract, branch))
    assert required_names, "no required contexts resolved — gate contract went vacuous"
    return [g for g in contract.gates if g.name in required_names]


def _matrix_job_keys(workflow: str) -> set[str]:
    """Job keys in ``workflow`` that carry a ``strategy.matrix`` (matrix-expanded)."""
    data = yaml.safe_load((_WORKFLOW_DIR / workflow).read_text(encoding="utf-8"))
    jobs = data.get("jobs", {}) if isinstance(data, dict) else {}
    return {
        key
        for key, spec in jobs.items()
        if isinstance(spec, dict)
        and (spec.get("strategy") or {}).get("matrix") is not None
    }


def _required_matrix_gates() -> list[Gate]:
    """Required gates whose producing job is matrix-expanded (fragile contexts)."""
    matrix_by_wf: dict[str, set[str]] = {}
    out: list[Gate] = []
    for gate in _required_gates():
        keys = matrix_by_wf.setdefault(gate.workflow, _matrix_job_keys(gate.workflow))
        if gate.job in keys:
            out.append(gate)
    return out


def _matrix_value(context: str) -> str:
    m = _MATRIX_CONTEXT_RE.match(context)
    assert m is not None, (
        f"required matrix context {context!r} is not of the form '<job> (<value>)' — "
        "cannot recover its matrix leg to verify producibility"
    )
    return m.group("value")


def _parse_set_literal(text: str, name: str) -> set[str]:
    """Extract a ``name = { ... }`` set literal from the discover-projects source."""
    m = re.search(rf"{name}\s*=\s*(\{{.*?\}})", text, re.DOTALL)
    assert m is not None, (
        f"could not locate the `{name}` set in {_QUALITY_WF} discover-projects "
        "scan — the guard cannot verify producibility against a scan it can't read"
    )
    value = ast.literal_eval(m.group(1))
    assert isinstance(value, set) and value, f"`{name}` parsed empty/non-set"
    return value


def _discover_projects_sets() -> tuple[set[str], set[str]]:
    text = _QUALITY_WF.read_text(encoding="utf-8")
    return _parse_set_literal(text, "markers"), _parse_set_literal(text, "ignored")


def _dir_has_marker(proj: Path, markers: set[str]) -> bool:
    """True when a marker file sits DIRECTLY in ``proj``.

    discover-projects adds ``path.parent`` for each marker file it finds, so the
    context ``<dir>`` is produced only if a marker lives in ``<dir>`` itself, not
    in a descendant.
    """
    if not proj.is_dir():
        return False
    for child in proj.iterdir():
        if child.is_file() and (
            child.name in markers or child.suffix in _MARKER_SUFFIXES
        ):
            return True
    return False


def _unproducible_dirs(
    dirs: set[str], markers: set[str], ignored: set[str]
) -> list[str]:
    """Subset of ``dirs`` that discover-projects would NOT emit against the tree.

    Pure so it can be exercised with synthetic inputs — a directory is
    unproducible if it does not exist, any path part is in ``ignored``, or it
    carries no marker file (the three edit vectors that orphan the context).
    """
    bad: list[str] = []
    for d in sorted(dirs):
        proj = _REPO_ROOT if d == "." else _REPO_ROOT / d
        parts: tuple[str, ...] = () if d == "." else Path(d).parts
        if (
            not proj.is_dir()
            or (set(parts) & ignored)
            or not _dir_has_marker(proj, markers)
        ):
            bad.append(d)
    return bad


def test_required_quality_matrix_contexts_are_producible() -> None:
    """Every required `quality (<dir>)` context is still emitted by the scan."""
    quality_dirs = {
        _matrix_value(g.name)
        for g in _required_matrix_gates()
        if g.job == _KNOWN_MATRIX_JOB
    }
    assert quality_dirs, (
        "no required `quality (<dir>)` contexts found — the fragile matrix gates "
        "vanished from gates.toml; this guard is now vacuous"
    )
    markers, ignored = _discover_projects_sets()
    orphaned = _unproducible_dirs(quality_dirs, markers, ignored)
    assert not orphaned, (
        "required branch-protection contexts would no longer be produced by "
        f"quality.yml discover-projects: {[f'quality ({d})' for d in orphaned]}. "
        "A required check that is never reported blocks the merge queue forever. "
        "Restore the marker file / markers-set entry, or drop the dir from `ignored`."
    )


def test_no_unknown_matrix_producer() -> None:
    """`quality` is the only matrix-expanded required producer; a new one must
    extend this guard rather than slip through unverified."""
    unknown = sorted(
        {g.job for g in _required_matrix_gates() if g.job != _KNOWN_MATRIX_JOB}
    )
    assert not unknown, (
        f"new matrix-expanded required producer job(s) {unknown} — extend this guard "
        "to verify their matrix values are producible, then allow the job here"
    )


def test_guard_flags_an_unproducible_dir() -> None:
    """The producibility check is live: bogus / ignored dirs are reported."""
    markers, ignored = _discover_projects_sets()
    assert _unproducible_dirs({"does-not-exist-xyz"}, markers, ignored) == [
        "does-not-exist-xyz"
    ]
    # A dir excluded by the scan's ignore-list is caught even if it exists.
    some_ignored = next(iter(ignored))
    assert _unproducible_dirs({some_ignored}, markers, ignored) == [some_ignored]
