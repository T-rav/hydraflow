"""Guard active pytest coverage against ignored tests.

Two blind spots this guard used to have, both proven by mutation before the
fix and both closed here.

**It scanned the wrong files.** The scan set was ``path.name.startswith("test")
or path.name == "conftest.py"``, but ``pyproject.toml`` sets ``python_files =
["test_*.py", "regression_*.py"]`` — the second glob added by #9801/#9872
precisely because 103 ``regression_*.py`` files had been silently uncollected
since creation. Collection was widened; this predicate never was. It scanned
1759 files where the corrected set is 1861, and the 103 collected files it
never opened held 111 ``xfail`` markers and one ``skipif`` that the guard
reported as zero. It also swept IN a file pytest never collects
(``tests/trust/adversarial/cases/.../tests_calc_scratch.py``), because
``startswith("test")`` matches ``tests_calc_scratch`` — wrong in both
directions at once.

The scan set is now derived from ``python_files`` at run time, so it cannot
drift from what pytest collects again. The rule is one sentence: **if pytest
does not collect it, this guard does not scan it** — which is also why
``tests/_adr_pin_support.py`` and friends need no allowlist entry.

**It matched spellings, not meanings.** The patterns were literal regexes
(``pytest\\.mark\\.skip``, ``pytest\\.skip\\(``). ``from pytest import mark``
followed by ``@mark.skip(...)`` walked straight through, and ``import pytest as
_pytest`` is live in three files today. Detection is now AST-based: imports are
resolved to their canonical dotted name, so every alias of a skipping construct
is caught and no new spelling has to be enumerated. It also stops matching text
inside strings and docstrings, which is why
``test_vitals_conformance_seam.py`` — a test whose *fixtures* contain the
literal ``pytest.importorskip(`` — is no longer a false positive.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

import pytest

from pytest_collection import collected_test_globs, is_collected_test_file
from tests.regressions.regression_issue_6435 import optional_dependency_roots

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = ROOT / "tests"

#: Scope label for an offender that sits at module level rather than in a test.
_MODULE_SCOPE = "<module>"


# ---------------------------------------------------------------------------
# Scan set — derived from pytest's own collection config, never re-spelled
# ---------------------------------------------------------------------------


def _in_scan_set(path: Path, globs: tuple[str, ...]) -> bool:
    """Scan what pytest collects, plus ``conftest.py``.

    ``conftest.py`` is not a test module and ``is_collected_test_file`` rightly
    says so — but a ``pytest.skip`` at conftest scope skips every test in the
    directory below it, which is the largest-blast-radius place in the tree to
    hide coverage. It is scanned here and nowhere else, so the shared helper
    stays an honest answer to "would pytest collect tests from this file?".
    """
    return path.name == "conftest.py" or is_collected_test_file(path.name, globs)


def active_test_files() -> list[Path]:
    """Every file under ``tests/`` that pytest collects, plus ``conftest.py``.

    Public on purpose: regression pins import this selector cross-module, and
    an underscore-private name would make that a hidden coupling.
    """
    this_file = Path(__file__).resolve()
    globs = collected_test_globs(ROOT)
    return sorted(
        path
        for path in TESTS_ROOT.rglob("*.py")
        if path.resolve() != this_file and _in_scan_set(path, globs)
    )


# ---------------------------------------------------------------------------
# Detection — resolve imports to canonical names instead of matching spellings
# ---------------------------------------------------------------------------

#: Canonical dotted names that suppress a test outright.
_SUPPRESSORS: dict[str, str] = {
    "pytest.mark.skip": "skip marker",
    "pytest.mark.skipif": "skip marker",
    "pytest.mark.xfail": "xfail marker",
    "pytest.skip": "runtime skip",
    "pytest.xfail": "runtime xfail",
    "unittest.skip": "unittest skip",
    "unittest.skipIf": "unittest skip",
    "unittest.skipUnless": "unittest skip",
    "unittest.expectedFailure": "unittest expected failure",
}

#: Modules whose members resolve to a canonical prefix when imported by name.
_FROM_IMPORT_ROOTS = frozenset({"pytest", "unittest"})

_COMMENTED_OUT = re.compile(
    r"^\s*#\s*("
    r"async\s+def\s+test_|"
    r"def\s+test_|"
    r"class\s+Test|"
    r"@pytest\.mark|"
    r"pytestmark\s*=|"
    r"assert\s+"
    r")"
)


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Local name -> canonical dotted path, for pytest/unittest bindings.

    This is what keys the guard on meaning instead of spelling:
    ``import pytest as _pytest`` and ``from pytest import mark as m`` both end
    up pointing at the same canonical names as the plain forms.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _FROM_IMPORT_ROOTS:
                    continue
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    # `import a.b` binds `a`, NOT `a.b`. Keying by the dotted
                    # string produced an entry no `ast.Name.id` can ever match,
                    # so `import unittest.mock` (live at tests/test_triage.py:7)
                    # left every later `unittest.skip` unresolvable — this
                    # guard's own F2 defect, one level down.
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] not in _FROM_IMPORT_ROOTS:
                continue
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _canonical(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """Resolve an attribute/name expression to its canonical dotted path."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _canonical(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def _scope_names(tree: ast.Module) -> dict[ast.AST, str]:
    """Innermost enclosing def/class name for every node.

    Offenders are keyed by test name rather than by line number: the
    grandfather set below has to survive edits above it, and this repo has
    already learned that line-window anchors go vacuous.
    """
    names: dict[ast.AST, str] = {}

    def descend(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = f"{scope}.{child.name}" if scope else child.name
                names[child] = inner
                descend(child, inner)
            else:
                names[child] = scope
                descend(child, scope)

    descend(tree, "")
    return names


def _importorskip_offence(node: ast.Call, optional: frozenset[str]) -> str | None:
    """Why this ``importorskip`` call is a hazard, or None if it is legitimate.

    ``pytest.importorskip`` is kept LEGITIMATE, deliberately. Skipping a module
    whose dependency a lane genuinely may not have installed is graceful
    degradation, and it is the pattern ``regression_issue_6435`` steers people
    toward — that guard forbids module-level imports of optional dependencies,
    so ``importorskip`` is the sanctioned way to write them.

    What is NOT legitimate is ``importorskip`` on a dependency that is always
    installed. It can never degrade gracefully, because the module can never be
    absent in a working environment; all it can do is delete a whole test
    module in silence when the environment is broken. The optional set comes
    from ``optional_dependency_roots()`` — the repo's existing public helper,
    reused rather than re-spelled, so the two guards cannot disagree about
    which dependency is optional.
    """
    if not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    module = first.value.split(".")[0]
    if module in optional:
        return None
    return (
        f"importorskip on {module!r}, which is not an optional dependency — "
        "it can only vanish this module when the environment is broken"
    )


def _offenders_in(path: Path, optional: frozenset[str]) -> list[tuple[str, str, str]]:
    """(scope, label, detail) for each suppressed-coverage site in *path*."""
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text, filename=str(path))
    aliases = _alias_map(tree)
    scopes = _scope_names(tree)
    found: list[tuple[str, str, str]] = []

    for node in ast.walk(tree):
        scope = scopes.get(node) or _MODULE_SCOPE
        if isinstance(node, ast.Call):
            if _canonical(node.func, aliases) == "pytest.importorskip":
                detail = _importorskip_offence(node, optional)
                if detail:
                    found.append((scope, "import-or-skip", detail))
            continue
        if not isinstance(node, ast.Attribute | ast.Name):
            continue
        canonical = _canonical(node, aliases)
        label = _SUPPRESSORS.get(canonical or "")
        if label:
            found.append((scope, label, canonical or ""))

    for lineno, line in enumerate(text.splitlines(), start=1):
        if _COMMENTED_OUT.search(line):
            found.append(
                (f"line {lineno}", "commented-out test/assertion", line.strip())
            )
    return found


# ---------------------------------------------------------------------------
# Grandfathered deferrals
# ---------------------------------------------------------------------------

#: The grandfather set is GONE, and that is the success condition, not an
#: omission. It held 107 deferred ``xfail`` markers — the #6408-#6975 batch of
#: pinned bugs that #9801/#9872's widened ``python_files`` first made visible.
#: Every one has since been fixed and its marker removed, so the set emptied,
#: and its own anti-vacuity test said what to do next: "If every deferral
#: really was resolved, delete the set and its two tests rather than leaving a
#: hollow gate."
#:
#: With nothing exempted, the scan below is unconditional: an ``xfail`` on an
#: active test is an offence, full stop. Re-introducing a grandfather list
#: would mean re-introducing the debt it existed to count down.


def _key(rel: str, scope: str) -> str:
    return f"{rel}::{scope}"


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def _scan() -> dict[str, list[tuple[str, str, str]]]:
    optional = optional_dependency_roots()
    results: dict[str, list[tuple[str, str, str]]] = {}
    for path in active_test_files():
        offenders = _offenders_in(path, optional)
        if offenders:
            results[path.relative_to(ROOT).as_posix()] = offenders
    return results


def test_active_tests_do_not_skip_xfail_or_comment_out_coverage() -> None:
    offenders: list[str] = []
    for rel, found in _scan().items():
        for scope, label, detail in found:
            offenders.append(f"{rel}::{scope}: {label}: {detail}")

    assert not offenders, (
        "Active tests must assert real contracts. Move deferred work into the "
        "active issue/PR workflow or out of pytest collection; do not hide it "
        "behind skip/xfail/commented tests:\n  " + "\n  ".join(sorted(offenders))
    )


def test_scan_set_covers_both_collected_file_shapes() -> None:
    """A wrong tomllib key path yields no globs, an empty scan, and a green gate.

    This is the only test that catches that failure mode, so it is not
    optional. It pins both shapes by name because the whole bug was a scan set
    that saw one of them and not the other.
    """
    names = [path.name for path in active_test_files()]
    assert names, "scan set is empty — the guard would pass while scanning nothing"
    assert any(fnmatch.fnmatch(n, "test_*.py") for n in names)
    assert any(fnmatch.fnmatch(n, "regression_*.py") for n in names)
    assert "conftest.py" in names


def test_scan_set_matches_pytests_own_collection_config() -> None:
    """The globs really do come from pyproject, not from a constant here."""
    globs = collected_test_globs(ROOT)
    assert globs, "python_files resolved empty — scan set would be conftest-only"
    assert set(globs) == {"test_*.py", "regression_*.py"}, (
        f"pytest now collects {globs}; the guard follows automatically, but "
        "confirm the grandfather set still covers what widened."
    )


#: (name, source, expected labels) — the spellings detection must resolve.
#:
#: Parametrised over the alias forms themselves rather than asserted once for
#: the plain spelling: the defect being fixed was a detector that recognised
#: ONE spelling of each construct, so a table of one is how it happens again.
#: The last two cases are the other direction — text that merely mentions a
#: marker is not a marker, which the previous line-regex could not tell apart.
_DETECTION_CASES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "module-level pytestmark",
        "import pytest\npytestmark = [pytest.mark.skip(reason='x')]\n",
        ["skip marker"],
    ),
    (
        "aliased module import",
        "import pytest as _p\n@_p.mark.xfail\ndef test_b(): pass\n",
        ["xfail marker"],
    ),
    (
        "from-import alias",
        "from pytest import mark as m\n@m.skipif(True, reason='x')\ndef test_c(): pass\n",
        ["skip marker"],
    ),
    (
        "unittest skip decorator",
        "from unittest import skip\n@skip('x')\ndef test_d(): pass\n",
        ["unittest skip"],
    ),
    (
        "unittest expectedFailure",
        "import unittest\n@unittest.expectedFailure\ndef test_e(): pass\n",
        ["unittest expected failure"],
    ),
    (
        "runtime skip call",
        "import pytest\ndef test_f():\n    pytest.skip('later')\n",
        ["runtime skip"],
    ),
    (
        "marker text inside a string is not a marker",
        "S = '@pytest.mark.skip(reason=1)'\ndef test_g(): pass\n",
        [],
    ),
    (
        "marker named in a docstring is not a marker",
        '"we used to pytest.mark.skip this"\ndef test_h(): pass\n',
        [],
    ),
    (
        "dotted import binds the top-level name",
        "import unittest.mock\nclass Foo:\n    @unittest.skip('r')\n    def test_i(self): pass\n",
        ["unittest skip"],
    ),
    (
        "dotted pytest import binds the top-level name",
        "import pytest.mark\n@pytest.mark.xfail\ndef test_j(): pass\n",
        ["xfail marker"],
    ),
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [(src, exp) for _, src, exp in _DETECTION_CASES],
    ids=[name for name, _, _ in _DETECTION_CASES],
)
def test_detection_resolves_every_spelling(
    source: str, expected: list[str], tmp_path: Path
) -> None:
    probe = tmp_path / "test_probe.py"
    probe.write_text(source, encoding="utf-8")

    labels = [label for _, label, _ in _offenders_in(probe, frozenset())]

    assert labels == expected


def test_offender_scope_is_the_test_name_not_a_line_number(tmp_path: Path) -> None:
    """The offender key is the test NAME, so it survives edits above it.

    The grandfather set keyed on this and is gone; the property still matters,
    because a line-number key would make every offender report churn on an
    unrelated edit above the marker.
    """
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "import pytest\n\n\nclass TestOuter:\n"
        "    @pytest.mark.xfail\n    def test_inner(self): pass\n",
        encoding="utf-8",
    )

    scopes = [scope for scope, _, _ in _offenders_in(probe, frozenset())]

    assert scopes == ["TestOuter.test_inner"]
