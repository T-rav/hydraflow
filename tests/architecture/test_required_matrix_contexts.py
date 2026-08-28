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

It runs in BOTH directions (#11715). The original check is *required ⊆
producible*, which fails loudly (the merge queue jams). The inverse — *produced
⊆ required* — is the dangerous one, because it fails SILENTLY: commit a
`package.json` / `Makefile` / `go.mod` / `pyproject.toml` into a new directory
and `discover-projects` starts emitting a `quality (<newdir>)` leg that is in
nobody's required list. `strict_required_status_checks_policy` is false and the
contexts are enumerated, so that leg can go RED without blocking the merge, and
nothing reddens to say so. `test_every_discovered_leg_is_required` closes it.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

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


def _unproducible_dirs(
    dirs: set[str], files: Iterable[str], markers: set[str], ignored: set[str]
) -> list[str]:
    """Subset of ``dirs`` that discover-projects would NOT emit for ``files``.

    Derived from :func:`_discovered_dirs`, the same pure function the inverse
    direction uses — so this module answers "what is in the tree?" exactly
    once, from the COMMITTED tree, in both directions (#11728).

    It previously walked the WORKING tree via ``proj.iterdir()`` while its
    inverse twin read ``git ls-files``. Two answers to one question, and the
    disagreement had a dangerous polarity: an **untracked** marker file left on
    a developer's disk made a dir look producible after its marker had been
    deleted from the committed tree. Locally green, red in CI on a clean
    checkout — a required context that is never reported, which jams the merge
    queue with no failing check to point at. That is the #10142 foot-gun this
    guard exists to prevent, reintroduced by the guard's own helper.

    Membership in ``_discovered_dirs`` subsumes all three original conditions:
    a dir that does not exist contributes no tracked marker, an ignored part is
    dropped by the scan mirror, and a dir with no marker never appears.
    """
    return sorted(set(dirs) - _discovered_dirs(files, markers, ignored))


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
    orphaned = _unproducible_dirs(quality_dirs, _tracked_files(), markers, ignored)
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
    marker = next(iter(markers))
    tracked = [f"services/real/{marker}"]

    # A dir with no marker anywhere in the committed tree.
    assert _unproducible_dirs({"does-not-exist-xyz"}, tracked, markers, ignored) == [
        "does-not-exist-xyz"
    ]
    # A dir excluded by the scan's ignore-list is caught even when its marker
    # IS committed — the scan drops it, so the context is never produced.
    some_ignored = next(iter(ignored))
    assert _unproducible_dirs(
        {some_ignored}, [f"{some_ignored}/{marker}"], markers, ignored
    ) == [some_ignored]
    # Control: a dir whose marker is committed is producible, so the guard must
    # NOT flag it. Without this the function could return every input and the
    # two assertions above would still pass.
    assert _unproducible_dirs({"services/real"}, tracked, markers, ignored) == []


def test_an_untracked_marker_cannot_mask_a_committed_deletion() -> None:
    """#11728, the regression: the answer comes from the COMMITTED tree.

    The forward guard used to walk the working tree. A marker file deleted from
    the committed tree but still present untracked on a developer's disk read
    as producible locally and orphaned in CI — the silent direction, because
    the required context simply never reports and no check goes red.

    Here the marker is absent from ``tracked`` while a stray file sits in the
    same directory. Only a committed-tree answer flags it.
    """
    markers, ignored = _discover_projects_sets()
    marker = next(iter(markers))
    committed_without_the_marker = ["services/svc/README.md", f"other/{marker}"]

    assert _unproducible_dirs(
        {"services/svc"}, committed_without_the_marker, markers, ignored
    ) == ["services/svc"], (
        "a dir whose marker is NOT in the committed tree was reported producible "
        "— the guard is reading something other than `git ls-files`"
    )
    # And it is producible the moment the marker is committed, so the assertion
    # above is about the marker and not about the directory name.
    assert (
        _unproducible_dirs(
            {"services/svc"},
            [*committed_without_the_marker, f"services/svc/{marker}"],
            markers,
            ignored,
        )
        == []
    )


def _tracked_files() -> list[str]:
    """Repo-relative POSIX paths of every file in the COMMITTED tree.

    Deliberately `git ls-files`, NOT a walk of the working tree. CI checks the
    committed tree out into a clean runner; the local working tree carries
    `.claude/worktrees/` and `.uv-cache/` that CI never sees, and walking it
    reports ~90 phantom legs instead of the real 2. A submodule appears here as
    a single gitlink entry rather than its contents, which matches the scan's
    own `.gitmodules`-based exclusion.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in out.split("\0") if path]


def _discovered_dirs(
    files: Iterable[str], markers: set[str], ignored: set[str]
) -> set[str]:
    """Matrix legs discover-projects would emit for ``files``.

    Pure, so it can be exercised with synthetic inputs. Mirrors the scan: a
    marker file contributes its PARENT directory (root becomes "."), any path
    with an ignored component is dropped, and `.sln`/`.csproj` count as markers
    by suffix.
    """
    dirs: set[str] = set()
    for name in files:
        path = PurePosixPath(name)
        if set(path.parts) & ignored:
            continue
        if path.name not in markers and path.suffix not in _MARKER_SUFFIXES:
            continue
        parent = str(path.parent)
        dirs.add("." if parent == "." else parent)
    return dirs


def _required_quality_dirs() -> set[str]:
    return {
        _matrix_value(g.name)
        for g in _required_matrix_gates()
        if g.job == _KNOWN_MATRIX_JOB
    }


def _unguarded_legs(
    files: Iterable[str], markers: set[str], ignored: set[str], required: set[str]
) -> list[str]:
    """Legs ``files`` would produce that ``required`` does not cover.

    Pure, and deliberately the ONLY place the comparison lives: against the real
    tree the two sets agree today, so the live assertion cannot falsify itself.
    `test_inverse_guard_reports_a_leg_nobody_requires` is its negative control —
    without it, this subtraction could be hollowed out and stay green.
    """
    return sorted(_discovered_dirs(files, markers, ignored) - set(required))


def test_every_discovered_leg_is_required() -> None:
    """Inverse direction: no `quality (<dir>)` leg runs ungated (#11715).

    The forward guard above stops a required context from being orphaned. This
    one stops a produced context from being un-required — the silent failure
    mode, where a new project marker spawns a matrix leg that may go red while
    the merge stays green.
    """
    markers, ignored = _discover_projects_sets()
    tracked = _tracked_files()
    assert _discovered_dirs(tracked, markers, ignored), (
        "discover-projects would emit no matrix legs against the committed tree "
        "— either `git ls-files` returned nothing or the markers set went "
        "vacuous; this guard cannot be trusted in that state"
    )
    unguarded = _unguarded_legs(tracked, markers, ignored, _required_quality_dirs())
    assert not unguarded, (
        "quality.yml discover-projects would emit matrix leg(s) "
        f"{[f'quality ({d})' for d in unguarded]} that branch protection does "
        "not require. Because strict_required_status_checks_policy is false and "
        "contexts are enumerated, those legs can go RED without blocking the "
        "merge. Add a [[gate]] for each in docs/standards/branch_protection/"
        "gates.toml and run `make gen-gates`, or add the directory to the scan's "
        "`ignored` set if it is not meant to be built."
    )


def test_inverse_guard_reports_a_leg_nobody_requires() -> None:
    """Negative control for the comparison itself, not just the leg scan."""
    markers, ignored = _discover_projects_sets()
    required = _required_quality_dirs()
    assert required, "no required quality legs — the comparison would be vacuous"
    marker = sorted(markers)[0]

    # A marker under a directory nobody requires is reported...
    assert _unguarded_legs(
        [marker, f"services/new-svc/{marker}"], markers, ignored, required
    ) == ["services/new-svc"]
    # ...while a leg that IS required is not.
    assert _unguarded_legs([marker], markers, ignored, required) == []


def test_inverse_guard_flags_a_new_marker_dir() -> None:
    """The inverse check is live: a synthetic marker dir produces a new leg."""
    markers, ignored = _discover_projects_sets()
    marker = sorted(markers)[0]
    # A marker committed under a brand-new directory yields that directory.
    assert _discovered_dirs([f"services/new-svc/{marker}"], markers, ignored) == {
        "services/new-svc"
    }
    # A marker at the repo root yields ".", exactly as the scan spells it.
    assert _discovered_dirs([marker], markers, ignored) == {"."}
    # The suffix markers count too.
    assert _discovered_dirs(["apps/App.csproj"], markers, ignored) == {"apps"}
    # Ignored path components are excluded, matching the scan.
    some_ignored = next(iter(ignored))
    assert _discovered_dirs([f"{some_ignored}/{marker}"], markers, ignored) == set()
    # Non-marker files contribute nothing.
    assert _discovered_dirs(["src/hydraflow_loop.py"], markers, ignored) == set()


def test_tracked_files_ignores_untracked_working_tree_files() -> None:
    """`_tracked_files` must be git-backed, not a working-tree walk.

    The difference is invisible until it is wrong: a walk of the working tree
    sweeps `.claude/worktrees/` (a whole second copy of the repo, markers and
    all) and `.uv-cache/`, neither of which CI ever checks out — ~90 phantom
    legs instead of the real 2. Probing with a real untracked file makes the
    distinction fail deterministically on any machine, including a clean CI
    checkout where the two happen to agree.
    """
    tracked = _tracked_files()
    assert tracked, "git ls-files returned nothing"
    assert "pyproject.toml" in tracked

    # Deliberately NOT tmp_path: the function under test reads _REPO_ROOT, so a
    # probe outside it could not tell a git read from a disk walk. pid-scoped so
    # concurrent xdist workers cannot collide, and removed in `finally`.
    probe = _REPO_ROOT / f"untracked-probe-{os.getpid()}.txt"
    probe.write_text("untracked\n", encoding="utf-8")
    try:
        assert probe.name not in set(_tracked_files()), (
            "_tracked_files() returned an UNTRACKED working-tree file — it is "
            "walking the disk instead of reading the committed tree, so local "
            "worktrees and caches will drown the real matrix legs"
        )
    finally:
        probe.unlink(missing_ok=True)
